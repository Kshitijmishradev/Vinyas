from __future__ import annotations

import re
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import requests

from architect.analyzers import SOURCE_EXTENSIONS

GITHUB_HOST = "github.com"
ARCHIVE_HOSTS = {GITHUB_HOST, "codeload.github.com"}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}$")


class RemoteSourceError(RuntimeError):
    code = "download_failed"


class InvalidRepositoryURL(RemoteSourceError):
    code = "invalid_repository_url"


class RepositoryNotFound(RemoteSourceError):
    code = "repository_not_found"


class RepositoryTooLarge(RemoteSourceError):
    code = "repository_too_large"


class ScanTimeout(RemoteSourceError):
    code = "scan_timeout"


class RemoteCancelled(RemoteSourceError):
    code = "cancelled"


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    repository: str

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repository}"

    def source(self, commit_sha: str | None = None) -> dict[str, str | None]:
        return {
            "kind": "github",
            "repository_url": self.url,
            "owner": self.owner,
            "repository": self.repository,
            "ref": "HEAD",
            "commit_sha": commit_sha,
        }


@dataclass(frozen=True, slots=True)
class RemoteLimits:
    max_download_bytes: int = 50 * 1024 * 1024
    max_archive_entries: int = 10_000
    max_source_files: int = 750
    max_source_bytes: int = 25 * 1024 * 1024
    max_file_bytes: int = 1024 * 1024
    timeout_seconds: int = 90


@dataclass(frozen=True, slots=True)
class RemoteSnapshot:
    root: Path
    commit_sha: str | None


Progress = Callable[[int, str], None]
Cancelled = Callable[[], bool]


def parse_github_url(value: str) -> GitHubRepository:
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise InvalidRepositoryURL("Enter a valid public GitHub repository URL.") from exc
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != GITHUB_HOST
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
    ):
        raise InvalidRepositoryURL("Use https://github.com/owner/repository.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise InvalidRepositoryURL("Use a repository URL without a branch or file path.")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if (
        not owner
        or not repository
        or owner in {".", ".."}
        or repository in {".", ".."}
        or not NAME_PATTERN.fullmatch(owner)
        or not NAME_PATTERN.fullmatch(repository)
    ):
        raise InvalidRepositoryURL("Enter a valid GitHub owner and repository name.")
    return GitHubRepository(owner=owner, repository=repository)


def download_github_snapshot(
    repository: GitHubRepository,
    workspace: Path,
    limits: RemoteLimits,
    *,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
    deadline: float | None = None,
    session: requests.Session | None = None,
) -> RemoteSnapshot:
    notify = progress or (lambda _value, _message: None)
    is_cancelled = cancelled or (lambda: False)
    stop_at = deadline if deadline is not None else time.monotonic() + limits.timeout_seconds
    client = session or requests.Session()
    archive_path = workspace / "repository.tar.gz"
    source_root = workspace / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    archive_url = f"https://github.com/{repository.owner}/{repository.repository}/archive/HEAD.tar.gz"

    notify(5, "Validating GitHub repository")
    response = _request_archive(client, archive_url, stop_at, is_cancelled)
    try:
        try:
            content_length = int(response.headers.get("Content-Length", "0") or 0)
        except ValueError:
            content_length = 0
        if content_length > limits.max_download_bytes:
            raise RepositoryTooLarge("Repository download exceeds the 50 MB limit.")
        downloaded = 0
        notify(10, "Downloading default branch snapshot")
        with archive_path.open("wb") as target:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                _guard(stop_at, is_cancelled)
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > limits.max_download_bytes:
                    raise RepositoryTooLarge("Repository download exceeds the 50 MB limit.")
                target.write(chunk)
    except requests.RequestException as exc:
        raise RemoteSourceError("GitHub download failed. Try again shortly.") from exc
    finally:
        response.close()

    notify(28, "Inspecting repository archive")
    commit_sha = _extract_archive(
        archive_path,
        source_root,
        repository,
        limits,
        stop_at,
        is_cancelled,
        notify,
    )
    return RemoteSnapshot(source_root, commit_sha)


def _request_archive(
    session: requests.Session,
    initial_url: str,
    deadline: float,
    cancelled: Cancelled,
) -> requests.Response:
    url = initial_url
    for _redirect in range(4):
        _guard(deadline, cancelled)
        try:
            response = session.get(
                url,
                stream=True,
                allow_redirects=False,
                timeout=(5, 20),
                headers={"User-Agent": "Vinyas/1.1"},
            )
        except requests.Timeout as exc:
            raise ScanTimeout("GitHub download timed out.") from exc
        except requests.RequestException as exc:
            raise RemoteSourceError("GitHub download failed. Try again shortly.") from exc
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RemoteSourceError("GitHub returned an invalid archive redirect.")
            url = urljoin(url, location)
            parsed = urlsplit(url)
            if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ARCHIVE_HOSTS:
                raise RemoteSourceError("GitHub returned an unsafe archive redirect.")
            continue
        if response.status_code == 404:
            response.close()
            raise RepositoryNotFound("Repository was not found or is not public.")
        if response.status_code >= 400:
            response.close()
            raise RemoteSourceError("GitHub could not provide this repository snapshot.")
        parsed = urlsplit(response.url or url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ARCHIVE_HOSTS:
            response.close()
            raise RemoteSourceError("GitHub returned an unsafe archive location.")
        return response
    raise RemoteSourceError("GitHub returned too many archive redirects.")


def _extract_archive(
    archive_path: Path,
    source_root: Path,
    repository: GitHubRepository,
    limits: RemoteLimits,
    deadline: float,
    cancelled: Cancelled,
    notify: Progress,
) -> str | None:
    entries = 0
    source_files = 0
    retained_bytes = 0
    archive_prefix: str | None = None
    commit_sha: str | None = None
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise RemoteSourceError("GitHub returned an unreadable repository archive.") from exc

    with archive:
        for member in archive:
            _guard(deadline, cancelled)
            entries += 1
            if entries > limits.max_archive_entries:
                raise RepositoryTooLarge("Repository archive contains too many entries.")
            path = PurePosixPath(member.name)
            unsafe_name = "\\" in member.name or any(ord(character) < 32 for character in member.name)
            if unsafe_name or path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
                raise RemoteSourceError("Repository archive contains an unsafe path.")
            prefix = path.parts[0]
            if archive_prefix is None:
                archive_prefix = prefix
                suffix = prefix.removeprefix(f"{repository.repository}-")
                commit_sha = suffix if SHA_PATTERN.fullmatch(suffix) else None
            elif prefix != archive_prefix:
                raise RemoteSourceError("Repository archive has an invalid root structure.")
            if member.issym() or member.islnk() or member.isdev():
                raise RemoteSourceError("Repository archive contains an unsupported link or device entry.")
            if member.isdir():
                continue
            if not member.isfile():
                raise RemoteSourceError("Repository archive contains an unsupported entry.")
            relative = PurePosixPath(*path.parts[1:])
            if not relative.parts or not _retained(relative):
                continue
            if member.size > limits.max_file_bytes:
                raise RepositoryTooLarge(f"{relative.as_posix()} exceeds the 1 MB file limit.")
            if relative.suffix.lower() in SOURCE_EXTENSIONS:
                source_files += 1
                if source_files > limits.max_source_files:
                    raise RepositoryTooLarge("Repository exceeds the 750 source-file limit.")
            retained_bytes += member.size
            if retained_bytes > limits.max_source_bytes:
                raise RepositoryTooLarge("Repository source exceeds the 25 MB limit.")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RemoteSourceError("Repository archive contains an unreadable file.")
            content = extracted.read(limits.max_file_bytes + 1)
            if len(content) != member.size or len(content) > limits.max_file_bytes:
                raise RepositoryTooLarge(f"{relative.as_posix()} exceeds the 1 MB file limit.")
            target = source_root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if entries % 100 == 0:
                notify(28 + min(12, entries // 100), "Extracting safe source files")
    if source_files == 0:
        raise RemoteSourceError("Repository contains no supported Python or JavaScript/TypeScript files.")
    notify(40, f"Prepared {source_files} source files")
    return commit_sha


def _retained(path: PurePosixPath) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() in SOURCE_EXTENSIONS
        or name in {"vinyas.yaml", "vinyas.yml", "architect.yaml", "architect.yml", "package.json"}
        or (name.startswith("tsconfig") and name.endswith(".json"))
    )


def _guard(deadline: float, cancelled: Cancelled) -> None:
    if cancelled():
        raise RemoteCancelled("Analysis cancelled.")
    if time.monotonic() >= deadline:
        raise ScanTimeout("Repository analysis exceeded the 90-second limit.")
