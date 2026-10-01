"""Pinned, forward-only migrations; each pending batch is atomic."""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from .db import connect

SCHEMA_DIR = Path(__file__).with_name('schema')
# Updated only when adding a reviewed migration, never from runtime file contents.
PINNED_HASHES: dict[str, str] = {'0001_core.sql': '4b8d67b71c181cf5b24ea9f7fdd2b4c9c46bc40a1ecdf1c213e096f1dfef5817', '0002_store.sql': '9f12c0ab09097253c1243af064e3beca401ad5695f40ede0b75dc72213221870', '0003_immutability.sql': 'ede4d88444243b43e67792407405514a7f71e87ced3e086f79ff44e7c618d23a', '0004_research.sql': '6d5124be6b6b977b764635c95df867f28a631e1461eaf1b15ce814475d53e563'}


def migration_files() -> list[tuple[Path, bytes]]:
    files = sorted(SCHEMA_DIR.glob('[0-9][0-9][0-9][0-9]_*.sql'))
    if [p.name for p in files] != list(PINNED_HASHES):
        raise RuntimeError('migration inventory mismatch')
    migrations = [(path, path.read_bytes()) for path in files]
    for path, data in migrations:
        if hashlib.sha256(data).hexdigest() != PINNED_HASHES[path.name]:
            raise RuntimeError(f'migration hash mismatch: {path.name}')
    return migrations


def verify_migrations(conn: sqlite3.Connection, files: list[tuple[Path, bytes]] | None = None) -> int:
    if files is None:
        files = migration_files()
    rows = list(conn.execute('SELECT version, filename, sha256 FROM sys_schema_migrations ORDER BY version'))
    expected = [(int(p.name[:4]), p.name, PINNED_HASHES[p.name]) for p, _ in files]
    if [tuple(r) for r in rows] != expected[:len(rows)]:
        raise RuntimeError('applied migration history mismatch')
    return len(rows)


def migration_statements(script: str) -> list[str]:
    """Split a pinned migration into complete SQLite statements."""
    statements: list[str] = []
    statement = ''
    for char in script:
        statement += char
        if char == ';' and sqlite3.complete_statement(statement):
            statements.append(statement)
            statement = ''
    if statement.strip():
        raise RuntimeError('incomplete migration statement')
    return statements


def execute_migration(conn: sqlite3.Connection, script: str) -> None:
    """Execute complete pinned statements without implicit commits."""
    for statement in migration_statements(script):
        keyword = statement.lstrip().split(None, 1)[0].upper()
        if keyword not in {'CREATE', 'INSERT', 'PRAGMA'}:
            raise RuntimeError('unsupported migration statement')
        conn.execute(statement)


def bootstrap_ledger_statement(first_migration: bytes) -> str:
    """Return the exact migration-ledger DDL from the already-hashed bytes."""
    for statement in migration_statements(first_migration.decode('utf-8')):
        normalized = ' '.join(statement.split()).upper()
        if normalized.startswith('CREATE TABLE IF NOT EXISTS SYS_SCHEMA_MIGRATIONS '):
            return statement
    raise RuntimeError('bootstrap migration ledger DDL missing')


def apply_migrations(db_path: str | Path) -> None:
    files = migration_files()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(bootstrap_ledger_statement(files[0][1]))
        count = verify_migrations(conn, files)
        for path, data in files[count:]:
            execute_migration(conn, data.decode('utf-8'))
            conn.execute('INSERT INTO sys_schema_migrations VALUES (?,?,?,?)',
                         (int(path.name[:4]), path.name, PINNED_HASHES[path.name], time.time_ns() // 1000))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_schema(conn: sqlite3.Connection) -> None:
    files = migration_files()
    if verify_migrations(conn, files) != len(files):
        raise ValueError('incomplete migrations')
    expected = sqlite3.connect(':memory:')
    try:
        for _, data in files:
            execute_migration(expected, data.decode('utf-8'))
        query = "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name != 'sqlite_sequence' ORDER BY type, name"
        if [tuple(row) for row in conn.execute(query)] != list(expected.execute(query)):
            raise ValueError('schema drift')
    finally:
        expected.close()
