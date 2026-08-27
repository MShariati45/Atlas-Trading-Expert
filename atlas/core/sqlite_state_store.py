from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable


class SQLiteStateStore:
    """Transactional state store for multi-process Atlas staging/runtime use.

    Uses SQLite WAL mode, a busy timeout, and IMMEDIATE transactions for writes.
    Values are JSON encoded to preserve the existing get/set/delete contract.
    This is intended to replace JsonFileStateStore for operational state while
    allowing tests and research tools to keep using the simpler store.
    """

    def __init__(self, path: str | Path = "runtime/atlas_state.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
                """
            )

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(value_json: str) -> Any:
        return json.loads(value_json)

    def get(self, key: str, default=None):
        with self._connect() as con:
            row = con.execute("SELECT value_json FROM state WHERE key=?", (str(key),)).fetchone()
        if row is None:
            return deepcopy(default)
        return deepcopy(self._decode(row[0]))

    def set(self, key: str, value: Any) -> None:
        encoded = self._encode(deepcopy(value))
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    """
                    INSERT INTO state(key,value_json,updated_at)
                    VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value_json=excluded.value_json,
                        updated_at=excluded.updated_at
                    """,
                    (str(key), encoded),
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def delete(self, key: str) -> None:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("DELETE FROM state WHERE key=?", (str(key),))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def update(self, key: str, updater: Callable[[Any], Any], default=None):
        """Atomic read-modify-write for values shared by multiple processes."""
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT value_json FROM state WHERE key=?", (str(key),)).fetchone()
                current = deepcopy(default) if row is None else self._decode(row[0])
                new_value = updater(deepcopy(current))
                encoded = self._encode(new_value)
                con.execute(
                    """
                    INSERT INTO state(key,value_json,updated_at)
                    VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value_json=excluded.value_json,
                        updated_at=excluded.updated_at
                    """,
                    (str(key), encoded),
                )
                con.execute("COMMIT")
                return deepcopy(new_value)
            except Exception:
                con.execute("ROLLBACK")
                raise
