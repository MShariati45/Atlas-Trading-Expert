import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from atlas2.model.data import RawBlob, SourceObservation
from atlas2.store import migrate
from atlas2.store.backup import backup, restore, verify
from atlas2.store.records import RunManifest, RunAttemptStart, RunAttemptEnd, RequestResult
from atlas2.store.repository import Store, StoreConflict, ConflictKind


class StoreFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'live')
        self.addCleanup(self.store.close)

    def runs(self):
        manifest = RunManifest('m1', '0'*64, None, 'REPLAY', '{}')
        start = RunAttemptStart('a1', 'm1', 1, 1, 1, '{}')
        end = RunAttemptEnd('a1', 'COMPLETED', '1'*64, None, 2)
        for model in (manifest, start, end):
            self.store.put(model)
        return manifest, start, end

    def test_pragmas_and_strict(self):
        c = self.store.conn
        for pragma, expected in [('journal_mode', 'wal'), ('synchronous', 2), ('foreign_keys', 1), ('trusted_schema', 0), ('busy_timeout', 5000), ('recursive_triggers', 1)]:
            self.assertEqual(c.execute(f'PRAGMA {pragma}').fetchone()[0], expected)
        for row in c.execute('PRAGMA table_list'):
            if not row['name'].startswith('sqlite_'):
                self.assertEqual(row['strict'], 1)

    def test_all_evidence_immutable_including_replace(self):
        self.runs()
        blob = self.store.put_blob(b'raw')
        self.store.request('actor', 'action', 'key', {}, 'result')
        self.store.seal('run_manifests', 'm1')
        self.store.put(SourceObservation('obs_'+'1'*64, blob.blob_sha256, 'src', 'v1', 'MANUAL_IMPORT', 1, 'comp_'+'2'*64))
        self.store.conn.execute("INSERT INTO sys_audit VALUES (1,1,'test','owner','ali',1,NULL,NULL,'{}','',?)", ('0'*64,))
        tables = ['raw_blobs', 'source_observations', 'run_manifests', 'run_attempt_starts', 'run_attempt_ends', 'sys_request_keys', 'sys_seals', 'sys_recovery_epochs', 'sys_audit', 'sys_schema_migrations']
        for table in tables:
            column = self.store.conn.execute(f'PRAGMA table_info({table})').fetchone()['name']
            for sql in [f'UPDATE {table} SET {column}={column}', f'DELETE FROM {table}', f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}']:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    self.store.conn.execute(sql)

    def test_identity_logical_and_terminal_conflicts(self):
        manifest, start, end = self.runs()
        self.assertEqual(self.store.put(start), ConflictKind.IDEMPOTENT_REPEAT)
        for model, kind in [(replace(manifest, mode='FORWARD'), ConflictKind.IDENTITY_CONFLICT), (replace(start, attempt_id='a2'), ConflictKind.LOGICAL_KEY_CONFLICT), (replace(end, status='FAILED'), ConflictKind.IDENTITY_CONFLICT)]:
            with self.assertRaises(StoreConflict) as error:
                self.store.put(model)
            self.assertEqual(error.exception.kind, kind)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("INSERT INTO run_attempt_ends VALUES ('a1','FAILED',NULL,NULL,3)")

    def test_request_retry_keeps_result_and_time(self):
        first = self.store.request('ali', 'write', 'k', {'x': 1}, 'original')
        self.assertEqual(first, self.store.request('ali', 'write', 'k', {'x': 1}, 'different'))
        with self.assertRaises(StoreConflict) as error:
            self.store.request('ali', 'write', 'k', {'x': 2}, 'other')
        self.assertEqual(error.exception.kind, ConflictKind.LOGICAL_KEY_CONFLICT)
        self.store.request('other', 'write', 'k', {'x': 2}, 'other')

    def test_validate_before_write(self):
        for model in [RawBlob('bad', 1), RunManifest('m', '0'*64, None, 'BAD', '{}'), RunAttemptStart('a', 'm', 1, True, 1, '{}')]:
            with self.assertRaises((ValueError, TypeError)):
                self.store.put(model)
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM run_manifests').fetchone()[0], 0)
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM raw_blobs').fetchone()[0], 0)

    def test_blob_repeats_corruption_and_missing(self):
        first = self.store.put_blob(b'hello')
        self.assertEqual(first, self.store.put_blob(b'hello'))
        self.assertEqual(self.store.blobs.read(first.blob_sha256), b'hello')
        (self.store.blobs.root / first.blob_sha256).write_bytes(b'corrupt')
        for operation in [lambda: self.store.blobs.read(first.blob_sha256), lambda: self.store.put_blob(b'hello'), lambda: verify(self.store.root)]:
            with self.assertRaises(ValueError):
                operation()
        with self.assertRaises(FileNotFoundError):
            self.store.put(RawBlob('0'*64, 1))

    def test_seals_reject_children_in_sql_and_repository(self):
        self.runs()
        digest = self.store.seal('run_manifests', 'm1')
        self.assertEqual(digest, self.store.seal('run_manifests', 'm1'))
        with self.assertRaises(StoreConflict) as error:
            self.store.put(RunAttemptStart('a2', 'm1', 1, 2, 3, '{}'))
        self.assertEqual(error.exception.kind, ConflictKind.SEAL_VIOLATION)
        self.store.put(RunManifest('m2', '0'*64, None, 'REPLAY', '{}'))
        self.store.put(RunAttemptStart('a2', 'm2', 1, 1, 3, '{}'))
        self.store.seal('run_attempt_starts', 'a2')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'SEAL_VIOLATION'):
            self.store.conn.execute("INSERT INTO run_attempt_ends VALUES ('a2','FAILED',NULL,NULL,4)")
        verify(self.store.root)

    def test_migration_tamper_and_unknown_history(self):
        schema = self.root / 'schema'
        shutil.copytree(migrate.SCHEMA_DIR, schema)
        with patch.object(migrate, 'SCHEMA_DIR', schema):
            file = schema / '0001_core.sql'
            file.write_text(file.read_text()+'\n')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                migrate.apply_migrations(self.store.path)
        self.store.conn.execute("INSERT INTO sys_schema_migrations VALUES (999,'unknown','0000000000000000000000000000000000000000000000000000000000000000',1)")
        with self.assertRaisesRegex(RuntimeError, 'history mismatch'):
            verify(self.store.root)

    def test_failed_migration_rolls_back_ddl_and_rows(self):
        schema = self.root / 'schema'
        shutil.copytree(migrate.SCHEMA_DIR, schema)
        bad = schema / f'{len(migrate.PINNED_HASHES)+1:04d}_failed.sql'
        bad.write_text('CREATE TABLE should_rollback(x INTEGER) STRICT; INSERT INTO should_rollback VALUES (1); INSERT INTO missing VALUES (1);')
        pins = dict(migrate.PINNED_HASHES)
        pins[bad.name] = hashlib.sha256(bad.read_bytes()).hexdigest()
        with patch.object(migrate, 'SCHEMA_DIR', schema), patch.object(migrate, 'PINNED_HASHES', pins):
            with self.assertRaises(sqlite3.OperationalError):
                migrate.apply_migrations(self.store.path)
        self.assertIsNone(self.store.conn.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchone())
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM sys_schema_migrations').fetchone()[0], len(migrate.PINNED_HASHES))
        verify(self.store.root)

    def test_backup_restore_without_original(self):
        self.runs()
        blob = self.store.put_blob(b'only in backup')
        self.store.seal('run_manifests', 'm1')
        saved = backup(self.store, self.root / 'backup')
        self.store.close()
        shutil.rmtree(self.store.root)
        restored = restore(saved, self.root / 'restored')
        verify(restored)
        with Store(restored) as store:
            self.assertEqual(store.blobs.read(blob.blob_sha256), b'only in backup')
            self.assertEqual(store.conn.execute('SELECT count(*) FROM run_attempt_ends').fetchone()[0], 1)
        with self.assertRaises(FileExistsError):
            restore(saved, restored)
        (saved / 'raw' / blob.blob_sha256).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            restore(saved, self.root / 'bad-restore')

    def test_blob_failed_publication_leaves_no_partial_file(self):
        with patch('atlas2.store.blobs.os.replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                self.store.put_blob(b'failed publication')
        self.assertEqual(list(self.store.blobs.root.iterdir()), [])
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM raw_blobs').fetchone()[0], 0)

    def test_migration_fresh_database_failure_is_atomic(self):
        schema = self.root / 'schema'
        shutil.copytree(migrate.SCHEMA_DIR, schema)
        file = schema / '0002_store.sql'
        file.write_text(file.read_text() + 'INSERT INTO missing VALUES (1);')
        pins = dict(migrate.PINNED_HASHES)
        pins[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
        fresh = self.root / 'fresh.sqlite3'
        with patch.object(migrate, 'SCHEMA_DIR', schema), patch.object(migrate, 'PINNED_HASHES', pins):
            with self.assertRaises(sqlite3.OperationalError):
                migrate.apply_migrations(fresh)
        conn = sqlite3.connect(fresh)
        try:
            self.assertEqual(list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'")), [])
        finally:
            conn.close()

    def test_independent_connections_observe_original_request(self):
        with Store(self.store.root) as other:
            original = self.store.request('ali', 'write', 'key', {'a': 1}, 'first')
            retry = other.request('ali', 'write', 'key', {'a': 1}, 'second')
            self.assertEqual(original, retry)

    def test_verify_detects_foreign_key_damage(self):
        self.store.conn.execute('PRAGMA foreign_keys=OFF')
        self.store.conn.execute("INSERT INTO run_attempt_ends VALUES ('missing','FAILED',NULL,NULL,1)")
        self.store.conn.execute('PRAGMA foreign_keys=ON')
        with self.assertRaisesRegex(ValueError, 'foreign key'):
            verify(self.store.root)

    def test_raw_connection_replace_without_recursive_triggers(self):
        self.runs()
        blob = self.store.put_blob(b'raw')
        self.store.put(SourceObservation('obs_'+'1'*64, blob.blob_sha256, 's', 'v', 'MANUAL_IMPORT', 1, 'comp_'+'2'*64))
        self.store.request('a', 'b', 'c', {}, 'r')
        self.store.seal('run_attempt_starts', 'a1')
        self.store.conn.execute("INSERT INTO sys_audit VALUES (1,1,'t','o','a',1,NULL,NULL,'{}','',?)", ('0'*64,))
        conn = sqlite3.connect(self.store.path, isolation_level=None)
        self.addCleanup(conn.close)
        conn.execute('PRAGMA recursive_triggers=OFF')
        self.assertEqual(conn.execute('PRAGMA recursive_triggers').fetchone()[0], 0)
        # P0-2 invariants apply to the original core evidence tables. Later-stage
        # migrations may add legitimately empty immutable tables.
        tables = ['raw_blobs', 'source_observations', 'run_manifests', 'run_attempt_starts',
                  'run_attempt_ends', 'sys_request_keys', 'sys_seals', 'sys_recovery_epochs',
                  'sys_audit', 'sys_schema_migrations']
        for table in tables:
            before = list(conn.execute(f'SELECT * FROM {table}'))
            self.assertTrue(before)
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                conn.execute(f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')
            self.assertEqual(list(conn.execute(f'SELECT * FROM {table}')), before)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT OR REPLACE INTO run_attempt_starts VALUES ('new','m1',1,1,1,'{}')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT OR REPLACE INTO sys_schema_migrations SELECT 999,filename,sha256,applied_at_us FROM sys_schema_migrations WHERE version=1")

    def test_verify_detects_dropped_triggers(self):
        for trigger in ('immut_run_manifests_update', 'sealed_manifest_children', 'immut_raw_blobs_insert'):
            sql = self.store.conn.execute('SELECT sql FROM sqlite_schema WHERE name=?', (trigger,)).fetchone()[0]
            self.store.conn.execute(f'DROP TRIGGER {trigger}')
            with self.subTest(trigger=trigger), self.assertRaisesRegex(ValueError, 'schema drift'):
                verify(self.store.root)
            self.store.conn.execute(sql)
        verify(self.store.root)

    def test_canonical_json_and_duplicate_keys(self):
        manifest, start, _ = self.runs()
        for text in ('{ "a":1}', '{"b":1,"a":2}', '{"a":1,"a":2}', '{"a":{"x":1,"x":2}}', '{"a":"\\u0061"}', '-0', '1.0'):
            for model in (replace(manifest, manifest_id='m2', content_json=text), replace(start, attempt_id='a2', attempt_no=2, code_ref_json=text)):
                before = self.store.conn.total_changes
                with self.subTest(text=text, model=type(model)), self.assertRaises(ValueError):
                    self.store.put(model)
                self.assertEqual(self.store.conn.total_changes, before)
        self.store.put(replace(manifest, manifest_id='m2', content_json='{"a":1,"b":2}'))
        self.store.put(replace(start, attempt_id='a2', attempt_no=2, code_ref_json='{"a":1}'))

    def test_request_result_requires_request_path(self):
        model = RequestResult('a', 'b', 'c', '0'*64, 'r', 1)
        with self.assertRaises(TypeError):
            self.store.put(model)
        self.assertEqual(self.store.conn.execute('SELECT count(*) FROM sys_request_keys').fetchone()[0], 0)
        self.assertEqual(self.store.request('a', 'b', 'c', {}, 'r').result_ref, 'r')

    def test_migration_executes_the_bytes_it_hashed_once(self):
        original = Path.read_bytes
        reads = {}
        def read(path):
            if path.parent == migrate.SCHEMA_DIR:
                reads[path.name] = reads.get(path.name, 0) + 1
                if reads[path.name] > 1:
                    return b'INSERT INTO missing VALUES (1);'
            return original(path)
        with patch.object(Path, 'read_bytes', read), patch.object(Path, 'read_text', side_effect=AssertionError('must execute hashed bytes')):
            migrate.apply_migrations(self.root / 'same-bytes.sqlite3')
        self.assertEqual(reads, dict.fromkeys(migrate.PINNED_HASHES, 1))

    def test_migration_hash_length_constraint(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'CHECK'):
            self.store.conn.execute("INSERT INTO sys_schema_migrations VALUES (999,'bad','short',1)")
        sql = self.store.conn.execute("SELECT sql FROM sqlite_schema WHERE name='sys_schema_migrations'").fetchone()[0]
        self.assertIn('CHECK(length(sha256)=64)', sql)

    def test_restore_fsyncs_files_and_directories(self):
        blobs = [self.store.put_blob(data) for data in (b'one', b'two')]
        saved = backup(self.store, self.root / 'backup')
        dest = self.root / 'restored'
        synced = []
        real_fsync = os.fsync
        def sync(fd):
            stat = os.fstat(fd)
            synced.append((stat.st_dev, stat.st_ino))
            real_fsync(fd)
        with patch('atlas2.store.backup.os.fsync', side_effect=sync):
            restore(saved, dest)
        for path in [dest, dest / 'raw', dest / 'atlas.sqlite3'] + [dest / 'raw' / b.blob_sha256 for b in blobs]:
            stat = path.stat()
            self.assertIn((stat.st_dev, stat.st_ino), synced)

    def test_restore_rejects_unsafe_paths_and_extra_blob(self):
        saved = backup(self.store, self.root / 'backup')
        manifest_path = saved / 'manifest.json'
        original = json.loads(manifest_path.read_text())
        for name in ('../outside', '/absolute'):
            manifest = {'format': 1, 'files': dict(original['files'], **{name: '0'*64})}
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'invalid backup path'):
                restore(saved, self.root / 'bad')
            self.assertFalse((self.root / 'bad').exists())
        data = b'extra'
        digest = hashlib.sha256(data).hexdigest()
        (saved / 'raw' / digest).write_bytes(data)
        original['files'][f'raw/{digest}'] = digest
        manifest_path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            restore(saved, self.root / 'bad')
        self.assertFalse((self.root / 'bad').exists())

    def test_restore_rejects_inside_source_and_existing_destination(self):
        saved = backup(self.store, self.root / 'backup')
        with self.assertRaisesRegex(ValueError, 'outside'):
            restore(saved, saved / 'nested')
        self.assertFalse((saved / 'nested').exists())
        with self.assertRaises(FileExistsError):
            restore(saved, self.store.root)
        verify(self.store.root)

    def test_invalid_observation_and_terminal_make_zero_writes(self):
        self.runs()
        blob = self.store.put_blob(b'raw')
        observation = SourceObservation('obs_'+'1'*64, blob.blob_sha256, 'src', 'v1', 'MANUAL_IMPORT', 1, 'comp_'+'2'*64)
        for model in (replace(observation, acquisition_kind='BAD'), replace(observation, acquired_at_us=True), RunAttemptEnd('a1', 'BAD', None, None, 2), RunAttemptEnd('a1', 'FAILED', None, None, True)):
            before = self.store.conn.total_changes
            with self.assertRaises((TypeError, ValueError)):
                self.store.put(model)
            self.assertEqual(self.store.conn.total_changes, before)

    def test_unknown_seal_kind_and_parent(self):
        before = self.store.conn.total_changes
        for kind, parent in (('unknown', 'm1'), ('run_manifests', 'missing'), ('run_attempt_starts', 'missing')):
            with self.assertRaises(ValueError):
                self.store.seal(kind, parent)
        self.assertEqual(self.store.conn.total_changes, before)

    def test_put_validates_once(self):
        model = RunManifest('m1', '0'*64, None, 'REPLAY', '{}')
        with patch.object(RunManifest, 'validate', autospec=True, side_effect=RunManifest.validate) as validate:
            self.store.put(model)
        validate.assert_called_once_with(model)
