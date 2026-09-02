from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class AnalysisStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with closing(self._connection()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                root TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT,
                result TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT,
                expires_at TEXT,
                error_code TEXT,
                client_hash TEXT
                )"""
            )
            self._add_missing_columns(connection)
            connection.execute(
                """CREATE TABLE IF NOT EXISTS rate_events (
                client_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS rate_events_client_time ON rate_events(client_hash, created_at)"
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _add_missing_columns(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(analyses)")}
        for name, kind in {
            "source": "TEXT",
            "expires_at": "TEXT",
            "error_code": "TEXT",
            "client_hash": "TEXT",
        }.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE analyses ADD COLUMN {name} {kind}")

    def create(
        self,
        root: str,
        *,
        source: dict[str, Any] | None = None,
        client_hash: str | None = None,
    ) -> dict[str, Any]:
        analysis_id = str(uuid.uuid4())
        now = _now()
        with closing(self._connection()) as connection, connection:
            connection.execute(
                """INSERT INTO analyses(
                id,root,status,created_at,updated_at,source,client_hash
                ) VALUES(?,?,?,?,?,?,?)""",
                (analysis_id, root, "queued", now, now, _json(source), client_hash),
            )
        return self.get(analysis_id) or {}

    def reserve_remote(
        self,
        root: str,
        source: dict[str, Any],
        client_hash: str,
        *,
        max_per_hour: int,
        max_active: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        since = (now_dt - timedelta(hours=1)).isoformat()
        analysis_id = str(uuid.uuid4())
        with self._lock, closing(self._connection()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM rate_events WHERE created_at < ?", (since,))
            recent = connection.execute(
                "SELECT COUNT(*) FROM rate_events WHERE client_hash=? AND created_at>=?",
                (client_hash, since),
            ).fetchone()[0]
            if recent >= max_per_hour:
                connection.rollback()
                return None, "rate_limit_exceeded"
            client_active = connection.execute(
                """SELECT COUNT(*) FROM analyses
                WHERE client_hash=? AND status IN ('queued','running')""",
                (client_hash,),
            ).fetchone()[0]
            if client_active:
                connection.rollback()
                return None, "client_job_active"
            active = connection.execute(
                "SELECT COUNT(*) FROM analyses WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if active >= max_active:
                connection.rollback()
                return None, "service_capacity_reached"
            connection.execute(
                """INSERT INTO analyses(
                id,root,status,created_at,updated_at,source,client_hash
                ) VALUES(?,?,?,?,?,?,?)""",
                (analysis_id, root, "queued", now, now, _json(source), client_hash),
            )
            connection.execute(
                "INSERT INTO rate_events(client_hash,created_at) VALUES(?,?)",
                (client_hash, now),
            )
            connection.commit()
        return self.get(analysis_id), None

    def get(self, analysis_id: str, include_result: bool = False) -> dict[str, Any] | None:
        columns = (
            "id,root,status,progress,message,error,cancel_requested,created_at,updated_at,"
            "source,expires_at,error_code"
        )
        if include_result:
            columns += ",result"
        with closing(self._connection()) as connection:
            row = connection.execute(
                f"SELECT {columns} FROM analyses WHERE id=?", (analysis_id,)
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["cancel_requested"] = bool(item["cancel_requested"])
        if item.get("source"):
            item["source"] = json.loads(item["source"])
        if include_result and item.get("result"):
            item["result"] = json.loads(item["result"])
        return item

    def update(self, analysis_id: str, **values: Any) -> None:
        if not values:
            return
        values["updated_at"] = _now()
        for key in ("result", "source"):
            if key in values and not isinstance(values[key], str):
                values[key] = _json(values[key])
        assignments = ",".join(f"{key}=?" for key in values)
        with self._lock, closing(self._connection()) as connection, connection:
            connection.execute(
                f"UPDATE analyses SET {assignments} WHERE id=?",
                (*values.values(), analysis_id),
            )

    def cancel(self, analysis_id: str) -> bool:
        if not self.get(analysis_id):
            return False
        self.update(analysis_id, cancel_requested=1)
        return True

    def cancelled(self, analysis_id: str) -> bool:
        item = self.get(analysis_id)
        return bool(item and item["cancel_requested"])

    def delete(self, analysis_id: str) -> bool:
        with closing(self._connection()) as connection, connection:
            cursor = connection.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
        return bool(cursor.rowcount)

    def delete_expired(self, now: str | None = None) -> int:
        current = now or _now()
        with self._lock, closing(self._connection()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM analyses WHERE expires_at IS NOT NULL AND expires_at<=?",
                (current,),
            )
        return cursor.rowcount

    def mark_interrupted(self, expires_at: str) -> int:
        now = _now()
        with self._lock, closing(self._connection()) as connection, connection:
            cursor = connection.execute(
                """UPDATE analyses SET status='failed', progress=0,
                message='Analysis interrupted by service restart',
                error='The analysis was interrupted. Please run it again.',
                error_code='service_restarted', expires_at=?, updated_at=?
                WHERE status IN ('queued','running')""",
                (expires_at, now),
            )
        return cursor.rowcount


def expiry_after(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def is_expired(item: dict[str, Any]) -> bool:
    value = item.get("expires_at")
    return bool(value and datetime.fromisoformat(value) <= datetime.now(timezone.utc))


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
