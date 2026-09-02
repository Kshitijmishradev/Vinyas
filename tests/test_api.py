from __future__ import annotations

import importlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from architect.remote_sources import RemoteSnapshot
from architect.storage import AnalysisStore, expiry_after


class ApiTests(unittest.TestCase):
    def test_versioned_job_api_and_root_confinement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            data = Path(directory) / "data"
            root.mkdir()
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            os.environ["VINYAS_ROOT"] = str(root)
            os.environ["VINYAS_DATA_DIR"] = str(data)
            os.environ["VINYAS_REMOTE_ENABLED"] = "true"
            module = importlib.import_module("architect.api_server")
            module.ALLOWED_ROOT = root
            module.DATA_DIR = data
            module.STORE = AnalysisStore(data / "analyses.sqlite3")

            with TestClient(module.app) as client:
                self.assertEqual(200, client.get("/api/v1/health").status_code)
                forbidden = client.post("/api/v1/analyses", json={"path": directory})
                self.assertEqual(403, forbidden.status_code)

                created = client.post("/api/v1/analyses", json={})
                self.assertEqual(202, created.status_code)
                analysis_id = created.json()["id"]
                status_payload = wait_for_job(client, analysis_id)
                self.assertEqual("complete", status_payload["status"])
                graph = client.get(f"/api/v1/analyses/{analysis_id}/graph")
                self.assertEqual(1, graph.json()["summary"]["files"])
                self.assertNotIn("source", graph.text)

    def test_public_github_job_metadata_cleanup_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            data = Path(directory) / "data"
            root.mkdir()
            os.environ["VINYAS_ROOT"] = str(root)
            os.environ["VINYAS_DATA_DIR"] = str(data)
            module = importlib.import_module("architect.api_server")
            module.ALLOWED_ROOT = root
            module.DATA_DIR = data
            module.STORE = AnalysisStore(data / "analyses.sqlite3")
            module.REMOTE_ENABLED = True
            workspaces: list[Path] = []

            def fake_download(_repository, workspace: Path, _limits, **_kwargs) -> RemoteSnapshot:
                workspaces.append(workspace)
                source = workspace / "source"
                source.mkdir()
                (source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
                return RemoteSnapshot(source, "a" * 40)

            with patch.object(module, "download_github_snapshot", side_effect=fake_download):
                with TestClient(module.app) as client:
                    invalid = client.post(
                        "/api/v1/analyses", json={"repository_url": "https://evil.example/a/b"}
                    )
                    self.assertEqual(400, invalid.status_code)
                    both = client.post(
                        "/api/v1/analyses",
                        json={"path": ".", "repository_url": "https://github.com/acme/demo"},
                    )
                    self.assertEqual(400, both.status_code)

                    created = client.post(
                        "/api/v1/analyses",
                        json={"repository_url": "https://github.com/acme/demo.git/"},
                    )
                    self.assertEqual(202, created.status_code)
                    payload = created.json()
                    self.assertEqual("github", payload["source"]["kind"])
                    self.assertNotIn(str(data), created.text)
                    status_payload = wait_for_job(client, payload["id"])
                    self.assertEqual("complete", status_payload["status"])
                    self.assertEqual("a" * 40, status_payload["source"]["commit_sha"])
                    self.assertIsNotNone(status_payload["expires_at"])
                    graph = client.get(f"/api/v1/analyses/{payload['id']}/graph").json()
                    self.assertEqual("https://github.com/acme/demo", graph["root"])
                    self.assertFalse(workspaces[0].exists())

                    module.STORE.update(payload["id"], expires_at=expiry_after(-1))
                    expired = client.get(f"/api/v1/analyses/{payload['id']}")
                    self.assertEqual(410, expired.status_code)


def wait_for_job(client: TestClient, analysis_id: str) -> dict[str, object]:
    payload: dict[str, object] = {}
    for _ in range(100):
        payload = client.get(f"/api/v1/analyses/{analysis_id}").json()
        if payload["status"] in {"complete", "failed", "cancelled"}:
            return payload
        time.sleep(0.01)
    return payload


if __name__ == "__main__":
    unittest.main()
