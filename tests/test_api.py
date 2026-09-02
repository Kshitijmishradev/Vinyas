from __future__ import annotations

import importlib
import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class ApiTests(unittest.TestCase):
    def test_versioned_job_api_and_root_confinement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            data = Path(directory) / "data"
            root.mkdir()
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            os.environ["ARCHITECT_ROOT"] = str(root)
            os.environ["ARCHITECT_DATA_DIR"] = str(data)
            module = importlib.import_module("architect.api_server")
            client = TestClient(module.app)

            self.assertEqual(200, client.get("/api/v1/health").status_code)
            forbidden = client.post("/api/v1/analyses", json={"path": directory})
            self.assertEqual(403, forbidden.status_code)

            created = client.post("/api/v1/analyses", json={})
            self.assertEqual(202, created.status_code)
            analysis_id = created.json()["id"]
            for _ in range(50):
                status = client.get(f"/api/v1/analyses/{analysis_id}").json()
                if status["status"] in {"complete", "failed"}:
                    break
                time.sleep(0.01)
            self.assertEqual("complete", status["status"])
            graph = client.get(f"/api/v1/analyses/{analysis_id}/graph")
            self.assertEqual(1, graph.json()["summary"]["files"])
            self.assertNotIn("source", graph.text)


if __name__ == "__main__":
    unittest.main()
