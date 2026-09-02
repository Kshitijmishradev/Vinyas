from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AnalysisStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with closing(self._connection()) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, root TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '', error TEXT, result TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, root: str) -> dict[str, Any]:
        analysis_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connection()) as connection, connection:
            connection.execute("INSERT INTO analyses(id,root,status,created_at,updated_at) VALUES(?,?,?,?,?)", (analysis_id, root, "queued", now, now))
        return self.get(analysis_id) or {}

    def get(self, analysis_id: str, include_result: bool = False) -> dict[str, Any] | None:
        columns = "*" if include_result else "id,root,status,progress,message,error,cancel_requested,created_at,updated_at"
        with closing(self._connection()) as connection:
            row = connection.execute(f"SELECT {columns} FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["cancel_requested"] = bool(item["cancel_requested"])
        if include_result and item.get("result"):
            item["result"] = json.loads(item["result"])
        return item

    def update(self, analysis_id: str, **values: Any) -> None:
        if not values:
            return
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        if "result" in values and not isinstance(values["result"], str):
            values["result"] = json.dumps(values["result"], separators=(",", ":"))
        assignments = ",".join(f"{key}=?" for key in values)
        with self._lock, closing(self._connection()) as connection, connection:
            connection.execute(f"UPDATE analyses SET {assignments} WHERE id=?", (*values.values(), analysis_id))

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
