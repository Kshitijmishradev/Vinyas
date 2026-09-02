from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from architect.storage import AnalysisStore, expiry_after


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

    def test_remote_reservation_limits_and_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / "analyses.sqlite3")
            source = {"kind": "github", "repository_url": "https://github.com/acme/demo"}
            first, reason = store.reserve_remote(
                source["repository_url"], source, "client-a", max_per_hour=3, max_active=2
            )
            self.assertIsNone(reason)
            self.assertEqual(source, first["source"])

            duplicate, reason = store.reserve_remote(
                source["repository_url"], source, "client-a", max_per_hour=3, max_active=2
            )
            self.assertIsNone(duplicate)
            self.assertEqual("client_job_active", reason)

            second, reason = store.reserve_remote(
                source["repository_url"], source, "client-b", max_per_hour=3, max_active=2
            )
            self.assertIsNone(reason)
            blocked, reason = store.reserve_remote(
                source["repository_url"], source, "client-c", max_per_hour=3, max_active=2
            )
            self.assertIsNone(blocked)
            self.assertEqual("service_capacity_reached", reason)

            store.update(first["id"], status="complete", expires_at=expiry_after(-1))
            self.assertEqual(1, store.delete_expired())
            self.assertIsNone(store.get(first["id"]))
            self.assertIsNotNone(store.get(second["id"]))

    def test_remote_hourly_rate_limit_counts_accepted_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / "analyses.sqlite3")
            source = {"kind": "github", "repository_url": "https://github.com/acme/demo"}

            for _ in range(3):
                job, reason = store.reserve_remote(
                    source["repository_url"], source, "client-a", max_per_hour=3, max_active=2
                )
                self.assertIsNone(reason)
                self.assertIsNotNone(job)
                store.update(job["id"], status="complete")

            blocked, reason = store.reserve_remote(
                source["repository_url"], source, "client-a", max_per_hour=3, max_active=2
            )
            self.assertIsNone(blocked)
            self.assertEqual("rate_limit_exceeded", reason)


if __name__ == "__main__":
    unittest.main()
