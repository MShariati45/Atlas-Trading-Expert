from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA trusted_schema=OFF")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA recursive_triggers=ON")
    expected = {'journal_mode': 'wal', 'synchronous': 2, 'foreign_keys': 1,
                'trusted_schema': 0, 'busy_timeout': 5000, 'recursive_triggers': 1}
    for pragma, value in expected.items():
        if conn.execute(f"PRAGMA {pragma}").fetchone()[0] != value:
            conn.close()
            raise RuntimeError(f"SQLite {pragma} could not be configured")
    return conn


def begin_immediate(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
