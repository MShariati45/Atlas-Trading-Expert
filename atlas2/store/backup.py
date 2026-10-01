"""Private local snapshots. Destinations must not already exist."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from .blobs import BlobStore, fsync_directory
from .db import connect
from .migrate import verify_schema
from .repository import Store, child_digest


def verify(root: str | Path) -> None:
    root = Path(root)
    if not (root / 'atlas.sqlite3').is_file():
        raise ValueError('missing database')
    conn = connect(root / 'atlas.sqlite3')
    try:
        conn.execute('BEGIN')
        if [r[0] for r in conn.execute('PRAGMA integrity_check')] != ['ok']:
            raise ValueError('SQLite integrity check failed')
        if list(conn.execute('PRAGMA foreign_key_check')):
            raise ValueError('foreign key check failed')
        verify_schema(conn)
        blobs = BlobStore(root / 'raw')
        for row in conn.execute('SELECT * FROM raw_blobs'):
            if len(blobs.read(row['blob_sha256'])) != row['byte_size']:
                raise ValueError('blob size mismatch')
        # Recompute seals on the same database snapshot.
        for row in conn.execute('SELECT * FROM sys_seals'):
            if child_digest(conn, row['aggregate_kind'], row['aggregate_id']) != row['child_set_digest']:
                raise ValueError('seal digest mismatch')
    finally:
        conn.close()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup(store: Store, destination: str | Path) -> Path:
    destination = Path(destination)
    if destination.resolve().is_relative_to(store.root.resolve()):
        raise ValueError('backup must be outside the source store')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        db = destination / 'atlas.sqlite3'
        target = sqlite3.connect(db)
        try:
            store.conn.backup(target)
            digests = [r[0] for r in target.execute('SELECT blob_sha256 FROM raw_blobs ORDER BY blob_sha256')]
        finally:
            target.close()
        blobs = BlobStore(destination / 'raw')
        for digest in digests:
            blobs.put(store.blobs.read(digest))
        verify(destination)
        # Close/checkpoint all connections before hashing the database file.
        conn = connect(db)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.close()
        files = {'atlas.sqlite3': _file_hash(db)}
        files.update({f'raw/{digest}': digest for digest in digests})
        manifest = {'format': 1, 'files': files}
        (destination / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        for path in (db, destination / 'manifest.json'):
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
        fsync_directory(destination)
        fsync_directory(destination.parent)
        return destination
    except BaseException:
        shutil.rmtree(destination)
        raise


def restore(source: str | Path, destination: str | Path) -> Path:
    source, destination = Path(source), Path(destination)
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('restore must be outside the source backup')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('invalid backup manifest')
    files = manifest['files']
    if 'atlas.sqlite3' not in files:
        raise ValueError('missing backup database')
    for name, digest in files.items():
        from atlas2.model.data import _digest
        _digest(digest)
        if name != 'atlas.sqlite3' and name != f'raw/{digest}':
            raise ValueError('invalid backup path')
        if _file_hash(source / name) != digest:
            raise ValueError('backup hash mismatch')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for name in files:
            target = destination / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source / name, target)
        verify(destination)
        conn = connect(destination / 'atlas.sqlite3')
        try:
            required = {'atlas.sqlite3'} | {f'raw/{r[0]}' for r in conn.execute('SELECT blob_sha256 FROM raw_blobs')}
            if set(files) != required:
                raise ValueError('backup blob inventory mismatch')
        finally:
            conn.close()
        for name in files:
            with (destination / name).open('rb') as stream:
                os.fsync(stream.fileno())
        fsync_directory(destination / 'raw')
        fsync_directory(destination)
        fsync_directory(destination.parent)
        return destination
    except BaseException:
        shutil.rmtree(destination)
        raise
