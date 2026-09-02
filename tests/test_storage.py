from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from architect.storage import AnalysisStore


class StorageTests(unittest.TestCase):
    def test_job_lifecycle_and_source_is_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / "analyses.sqlite3")
            item = store.create("/repo")
            store.update(item["id"], status="complete", progress=100, result={"files": [], "summary": {}})
            saved = store.get(item["id"], include_result=True)
            self.assertEqual("complete", saved["status"])
            self.assertEqual([], saved["result"]["files"])
            self.assertNotIn("source", saved["result"])
            self.assertTrue(store.delete(item["id"]))


if __name__ == "__main__":
    unittest.main()
