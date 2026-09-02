from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from architect.remote_sources import (
    GitHubRepository,
    InvalidRepositoryURL,
    RemoteLimits,
    RemoteSourceError,
    RepositoryTooLarge,
    ScanTimeout,
    download_github_snapshot,
    parse_github_url,
)


class FakeResponse:
    def __init__(
        self,
        content: bytes = b"",
        *,
        status: int = 200,
        url: str = "https://codeload.github.com/acme/demo/tar.gz/HEAD",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status
        self.url = url
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.content[index : index + chunk_size] for index in range(0, len(self.content), chunk_size)]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> FakeResponse:
        self.urls.append(url)
        return self.responses.pop(0)


class RemoteSourceTests(unittest.TestCase):
    def test_github_url_normalization(self) -> None:
        repository = parse_github_url(" https://github.com/Acme/demo.git/ ")
        self.assertEqual("Acme", repository.owner)
        self.assertEqual("demo", repository.repository)
        self.assertEqual("https://github.com/Acme/demo", repository.url)

    def test_github_url_rejects_unsafe_forms(self) -> None:
        values = [
            "http://github.com/acme/demo",
            "https://www.github.com/acme/demo",
            "https://evil.example/acme/demo",
            "https://user:secret@github.com/acme/demo",
            "https://github.com:443/acme/demo",
            "https://github.com/acme/demo/tree/main",
            "https://github.com/acme/demo?tab=readme",
            "https://github.com/acme/demo#readme",
            "https://github.com/acme/%2e%2e",
            "https://github.com/acme",
        ]
        for value in values:
            with self.subTest(value=value), self.assertRaises(InvalidRepositoryURL):
                parse_github_url(value)

    def test_download_extracts_only_safe_analysis_inputs(self) -> None:
        sha = "a" * 40
        archive = make_archive(
            {
                f"demo-{sha}/src/app.py": b"from . import model\n",
                f"demo-{sha}/src/model.py": b"VALUE = 1\n",
                f"demo-{sha}/tsconfig.json": b"{}",
                f"demo-{sha}/README.md": b"not retained",
                f"demo-{sha}/image.png": b"not retained",
            }
        )
        redirect = FakeResponse(status=302, url="https://github.com/acme/demo/archive/HEAD.tar.gz", headers={"Location": "https://codeload.github.com/acme/demo/tar.gz/HEAD"})
        response = FakeResponse(archive, headers={"Content-Length": str(len(archive))})
        session = FakeSession([redirect, response])
        with tempfile.TemporaryDirectory() as directory:
            snapshot = download_github_snapshot(
                GitHubRepository("acme", "demo"),
                Path(directory),
                RemoteLimits(),
                session=session,  # type: ignore[arg-type]
            )
            self.assertEqual(sha, snapshot.commit_sha)
            self.assertTrue((snapshot.root / "src/app.py").is_file())
            self.assertTrue((snapshot.root / "tsconfig.json").is_file())
            self.assertFalse((snapshot.root / "README.md").exists())
            self.assertEqual(2, len(session.urls))

    def test_download_rejects_size_limits(self) -> None:
        response = FakeResponse(b"123456", headers={"Content-Length": "6"})
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RepositoryTooLarge):
            download_github_snapshot(
                GitHubRepository("acme", "demo"),
                Path(directory),
                RemoteLimits(max_download_bytes=5),
                session=FakeSession([response]),  # type: ignore[arg-type]
            )
        self.assertTrue(response.closed)

    def test_download_rejects_traversal_and_links(self) -> None:
        unsafe_archives = [
            make_archive({"demo-root/../escape.py": b"VALUE = 1\n"}),
            make_link_archive("demo-root/link.py", "../../escape.py"),
        ]
        for content in unsafe_archives:
            with self.subTest(), tempfile.TemporaryDirectory() as directory, self.assertRaises(RemoteSourceError):
                download_github_snapshot(
                    GitHubRepository("acme", "demo"),
                    Path(directory),
                    RemoteLimits(),
                    session=FakeSession([FakeResponse(content)]),  # type: ignore[arg-type]
                )

    def test_download_rejects_source_file_count(self) -> None:
        archive = make_archive(
            {"demo-root/one.py": b"x=1\n", "demo-root/two.py": b"x=2\n"}
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RepositoryTooLarge):
            download_github_snapshot(
                GitHubRepository("acme", "demo"),
                Path(directory),
                RemoteLimits(max_source_files=1),
                session=FakeSession([FakeResponse(archive)]),  # type: ignore[arg-type]
            )

    def test_download_honors_timeout_and_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ScanTimeout):
            download_github_snapshot(
                GitHubRepository("acme", "demo"),
                Path(directory),
                RemoteLimits(),
                deadline=0,
                session=FakeSession([]),  # type: ignore[arg-type]
            )

        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RemoteSourceError) as caught:
            download_github_snapshot(
                GitHubRepository("acme", "demo"),
                Path(directory),
                RemoteLimits(),
                cancelled=lambda: True,
                session=FakeSession([]),  # type: ignore[arg-type]
            )
        self.assertEqual("cancelled", caught.exception.code)


def make_archive(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def make_link_archive(name: str, target: str) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.type = tarfile.SYMTYPE
        info.linkname = target
        archive.addfile(info)
    return stream.getvalue()


if __name__ == "__main__":
    unittest.main()
