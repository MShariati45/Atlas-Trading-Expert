import errno
import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas2.hardening.manifest import FX_EURUSD_6W, P0_DOD_TESTS, assert_identity_graph_acyclic
from atlas2.store.audit import (
    append_external_checkpoint,
    audit_head,
    external_checkpoint_record,
    read_latest_external_checkpoint,
    verify_audit_chain,
)
from atlas2.store.backup import (
    RecoveryForkCheckpointError, StorageFullError, backup, restore, verify,
)
from atlas2.store.hardening import record_hardware_baseline
from atlas2.store import migrate
from atlas2.store.repository import Store
from atlas2.store.retention import BackupRetentionPolicy, DEFAULT_BACKUP_RETENTION


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "live")
        self.addCleanup(self.store.close)

    def test_audit_chain_request_and_verify(self):
        self.store.request("ali", "hardening.test", "k1", {"x": 1}, "result")
        self.store.request("ali", "hardening.test", "k2", {"x": 2}, "result2")
        seq, digest = verify_audit_chain(self.store.conn)
        self.assertEqual(seq, 2)
        self.assertEqual(audit_head(self.store.conn), (2, digest))
        verify(self.store.root)

    def test_format2_backup_checkpoint_restore_records_recovery_epoch(self):
        self.store.request("ali", "backup.test", "k", {"x": 1}, "result")
        self.store.put_blob(b"backup raw")
        policy = self.root / "policy.json"
        policy.write_text('{"mode":"P0"}', encoding="utf-8")
        lockfile = self.root / "requirements.lock"
        lockfile.write_text("none\n", encoding="utf-8")
        checkpoint = self.root / "external-checkpoints.jsonl"

        saved = backup(
            self.store,
            self.root / "backup",
            config_policy_files={"policy.json": policy},
            code_ref={"commit": "test"},
            lockfile=lockfile,
            tzdata_version="test-tz",
            external_checkpoint_path=checkpoint,
        )
        manifest = json.loads((saved / "manifest.json").read_text())
        self.assertEqual(manifest["format"], 2)
        self.assertEqual(manifest["code_ref"], {"commit": "test"})
        self.assertEqual(manifest["tzdata_version"], "test-tz")
        latest = read_latest_external_checkpoint(checkpoint)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["backup_name"], "backup")

        restored = restore(
            saved,
            self.root / "restored",
            external_checkpoint_path=checkpoint,
        )
        verify(restored)
        with Store(restored) as recovered:
            epochs = list(
                recovered.conn.execute(
                    "SELECT * FROM sys_recovery_epochs ORDER BY epoch"
                )
            )
            self.assertEqual(len(epochs), 2)
            self.assertEqual(epochs[-1]["missing_tail"], "NONE")
            self.assertEqual(
                epochs[-1]["external_checkpoint_hash"],
                manifest["audit_head"]["hash"],
            )
            self.assertEqual(
                recovered.conn.execute(
                    "SELECT event_type FROM sys_audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()[0],
                "RESTORE",
            )

    def test_restore_without_checkpoint_is_honestly_unknown(self):
        self.store.request("ali", "backup.test", "k", {}, "result")
        saved = backup(self.store, self.root / "backup")
        restored = restore(saved, self.root / "restored")
        with Store(restored) as recovered:
            latest = recovered.conn.execute(
                "SELECT * FROM sys_recovery_epochs ORDER BY epoch DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(latest["missing_tail"], "UNKNOWN")
            self.assertIsNone(latest["external_checkpoint_hash"])

    def test_shared_checkpoint_log_marks_older_restore_known_range(self):
        checkpoint = self.root / "checkpoint.jsonl"
        first = backup(
            self.store, self.root / "backup-a",
            external_checkpoint_path=checkpoint,
        )
        self.store.request("ali", "change", "k", {"n": 1}, "r")
        backup(
            self.store, self.root / "backup-b",
            external_checkpoint_path=checkpoint,
        )
        restored = restore(
            first, self.root / "restored",
            external_checkpoint_path=checkpoint,
        )
        with Store(restored) as recovered:
            latest = recovered.conn.execute(
                "SELECT * FROM sys_recovery_epochs ORDER BY epoch DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(latest["missing_tail"], "KNOWN_RANGE")

    def test_known_range_restore_requires_new_checkpoint_log_for_future_backups(self):
        checkpoint = self.root / "checkpoint.jsonl"
        first = backup(
            self.store,
            self.root / "backup-a",
            external_checkpoint_path=checkpoint,
        )
        self.store.request("ali", "change", "k", {"n": 1}, "r")
        backup(
            self.store,
            self.root / "backup-b",
            external_checkpoint_path=checkpoint,
        )
        restored = restore(
            first,
            self.root / "restored",
            external_checkpoint_path=checkpoint,
        )
        with Store(restored) as recovered:
            with self.assertRaisesRegex(
                RecoveryForkCheckpointError,
                "recovery fork requires a new external checkpoint log",
            ):
                backup(
                    recovered,
                    self.root / "fork-backup-same-log",
                    external_checkpoint_path=checkpoint,
                )
            self.assertTrue((self.root / "fork-backup-same-log").is_dir())
            verify(self.root / "fork-backup-same-log")

            fresh_log = self.root / "fork-checkpoint.jsonl"
            saved = backup(
                recovered,
                self.root / "fork-backup-new-log",
                external_checkpoint_path=fresh_log,
            )
            verify(saved)
            latest = read_latest_external_checkpoint(fresh_log)
            self.assertIsNotNone(latest)
            self.assertEqual(latest["backup_name"], "fork-backup-new-log")

    def test_restore_rejects_unrelated_nonnewer_checkpoint(self):
        saved = backup(self.store, self.root / "backup")
        checkpoint = self.root / "other-checkpoint.jsonl"
        append_external_checkpoint(
            checkpoint,
            external_checkpoint_record(
                manifest_digest="f" * 64,
                audit_seq=0,
                audit_hash="f" * 64,
                backup_name="other",
            ),
        )
        with self.assertRaisesRegex(ValueError, "checkpoint manifest mismatch"):
            restore(
                saved, self.root / "restored",
                external_checkpoint_path=checkpoint,
            )
        self.assertFalse((self.root / "restored").exists())

    def test_ancestor_checkpoint_from_other_manifest_is_accepted_as_behind(self):
        self.store.request("ali", "ancestor", "k", {"x": 1}, "r")
        saved = backup(self.store, self.root / "backup")
        checkpoint = self.root / "ancestor-checkpoint.jsonl"
        append_external_checkpoint(
            checkpoint,
            external_checkpoint_record(
                manifest_digest="d" * 64,
                audit_seq=0,
                audit_hash="0" * 64,
                backup_name="ancestor",
            ),
        )
        restored = restore(
            saved,
            self.root / "restored",
            external_checkpoint_path=checkpoint,
        )
        with Store(restored) as recovered:
            latest = recovered.conn.execute(
                "SELECT * FROM sys_recovery_epochs ORDER BY epoch DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(latest["missing_tail"], "UNKNOWN")
            self.assertEqual(latest["external_checkpoint_hash"], "0" * 64)

    def test_higher_unrelated_checkpoint_is_unknown_not_known_range(self):
        saved = backup(self.store, self.root / "backup")
        checkpoint = self.root / "foreign-later.jsonl"
        append_external_checkpoint(
            checkpoint,
            external_checkpoint_record(
                manifest_digest="e" * 64,
                audit_seq=9,
                audit_hash="f" * 64,
                backup_name="foreign-later",
            ),
        )
        restored = restore(
            saved,
            self.root / "restored",
            external_checkpoint_path=checkpoint,
        )
        with Store(restored) as recovered:
            latest = recovered.conn.execute(
                "SELECT * FROM sys_recovery_epochs ORDER BY epoch DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(latest["missing_tail"], "UNKNOWN")
            self.assertEqual(latest["external_checkpoint_hash"], "f" * 64)

    def test_disk_full_backup_not_published_and_live_store_survives(self):
        self.store.put_blob(b"raw that must be copied")
        destination = self.root / "backup"
        failure = OSError(errno.ENOSPC, "injected disk full")
        with patch("atlas2.store.backup.BlobStore.put", side_effect=failure):
            with self.assertRaisesRegex(StorageFullError, "disk full"):
                backup(self.store, destination)
        self.assertFalse(destination.exists())
        verify(self.store.root)

    def test_atomic_backup_publish_failure_leaves_no_visible_or_temp_package(self):
        destination = self.root / "backup"
        with patch("atlas2.store.backup.os.replace", side_effect=OSError("rename failed")):
            with self.assertRaisesRegex(OSError, "rename failed"):
                backup(self.store, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".backup.tmp-*")), [])

    def test_backup_checkpoint_failure_keeps_verified_backup(self):
        destination = self.root / "backup"
        with patch(
            "atlas2.store.backup.append_external_checkpoint",
            side_effect=OSError("checkpoint failed"),
        ):
            with self.assertRaisesRegex(OSError, "checkpoint failed"):
                backup(
                    self.store,
                    destination,
                    external_checkpoint_path=self.root / "checkpoint.jsonl",
                )
        self.assertTrue(destination.is_dir())
        verify(destination)

    def test_checkpoint_append_fails_closed_on_torn_tail(self):
        target = self.root / "checkpoint.jsonl"
        first = external_checkpoint_record(
            manifest_digest="1" * 64,
            audit_seq=0,
            audit_hash="0" * 64,
            backup_name="first",
        )
        append_external_checkpoint(target, first)
        with target.open("ab") as stream:
            stream.write(b'{"torn"')
            stream.flush()
            os.fsync(stream.fileno())
        before = target.read_bytes()
        second = external_checkpoint_record(
            manifest_digest="2" * 64,
            audit_seq=1,
            audit_hash="2" * 64,
            backup_name="second",
            previous_checkpoint=first,
        )
        with self.assertRaisesRegex(ValueError, "torn external checkpoint tail"):
            append_external_checkpoint(target, second)
        self.assertEqual(target.read_bytes(), before)

    def test_checkpoint_append_rejects_stale_parent_after_intervening_append(self):
        target = self.root / "checkpoint.jsonl"
        first = external_checkpoint_record(
            manifest_digest="1" * 64,
            audit_seq=0,
            audit_hash="0" * 64,
            backup_name="first",
        )
        append_external_checkpoint(target, first)
        second = external_checkpoint_record(
            manifest_digest="2" * 64,
            audit_seq=1,
            audit_hash="2" * 64,
            backup_name="second",
            previous_checkpoint=first,
        )
        append_external_checkpoint(target, second)
        stale = external_checkpoint_record(
            manifest_digest="3" * 64,
            audit_seq=2,
            audit_hash="3" * 64,
            backup_name="stale",
            previous_checkpoint=first,
        )
        with self.assertRaisesRegex(ValueError, "append lineage mismatch"):
            append_external_checkpoint(target, stale)

    def test_checkpoint_fsync_failure_is_not_silent(self):
        target = self.root / "checkpoint.jsonl"
        record = external_checkpoint_record(
            manifest_digest="0" * 64,
            audit_seq=0,
            audit_hash="0" * 64,
            backup_name="backup",
        )
        with patch("atlas2.store.audit.os.fsync", side_effect=OSError("fsync failed")):
            with self.assertRaisesRegex(OSError, "fsync failed"):
                append_external_checkpoint(target, record)

    def test_format1_restore_applies_pending_pinned_migrations(self):
        schema9 = self.root / "schema9"
        schema9.mkdir()
        names = list(migrate.PINNED_HASHES)[:9]
        pins9 = {name: migrate.PINNED_HASHES[name] for name in names}
        for name in names:
            shutil.copy2(migrate.SCHEMA_DIR / name, schema9 / name)

        source = self.root / "format1-backup"
        source.mkdir()
        db = source / "atlas.sqlite3"
        with patch.object(migrate, "SCHEMA_DIR", schema9), patch.object(
            migrate, "PINNED_HASHES", pins9
        ):
            migrate.apply_migrations(db)

        conn = sqlite3.connect(db)
        try:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM sys_schema_migrations").fetchone()[0],
                9,
            )
        finally:
            conn.close()

        digest = hashlib.sha256(db.read_bytes()).hexdigest()
        (source / "manifest.json").write_text(
            json.dumps(
                {"format": 1, "files": {"atlas.sqlite3": digest}},
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        restored = restore(source, self.root / "format1-restored")
        verify(restored)
        conn = sqlite3.connect(restored / "atlas.sqlite3")
        try:
            self.assertEqual(
                conn.execute("SELECT count(*) FROM sys_schema_migrations").fetchone()[0],
                len(migrate.PINNED_HASHES),
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT name FROM sqlite_schema "
                    "WHERE type='table' AND name='sys_hardware_baselines'"
                ).fetchone()
            )
        finally:
            conn.close()

    def test_hardware_baseline_recorded_without_threshold(self):
        baseline_id, content = record_hardware_baseline(
            self.store, captured_at_us=1_000_000
        )
        self.assertTrue(baseline_id.startswith("hwb_"))
        self.assertIn("platform_system", content)
        self.assertIn("logical_cpu_count", content)
        self.assertIn("disk_free_bytes", content)
        row = self.store.conn.execute(
            "SELECT * FROM sys_hardware_baselines WHERE baseline_id=?",
            (baseline_id,),
        ).fetchone()
        self.assertEqual(row["captured_at_us"], 1_000_000)
        with self.assertRaises(Exception):
            self.store.conn.execute(
                "UPDATE sys_hardware_baselines SET captured_at_us=captured_at_us "
                "WHERE baseline_id=?",
                (baseline_id,),
            )

    def test_application_id_is_verified(self):
        verify(self.store.root)
        self.store.conn.execute("PRAGMA application_id=0")
        with self.assertRaisesRegex(ValueError, "application_id"):
            verify(self.store.root)

    def test_fx_eurusd_6w_manifest_spans_both_dst_transitions(self):
        manifest = FX_EURUSD_6W
        self.assertEqual(manifest["name"], "fx_eurusd_6w")
        self.assertEqual(manifest["instrument_id"], "EURUSD")
        self.assertEqual(manifest["timeframes"], ["M1", "M15"])
        self.assertEqual(
            manifest["end_us"] - manifest["start_us"],
            42 * 24 * 60 * 60 * 1_000_000,
        )
        for marker in manifest["dst_markers_us"]:
            self.assertGreater(marker, manifest["start_us"])
            self.assertLess(marker, manifest["end_us"])
        self.assertIn("DELAYED_CONSTITUENTS", manifest["scenarios"])
        self.assertIn("OVERLAPPING_EXPORTS", manifest["scenarios"])
        self.assertIn("CALENDAR_UNKNOWN", manifest["scenarios"])
        self.assertIn("DISTINCT_SAME_BAR_OCCURRENCES", manifest["scenarios"])

    def test_p0_dod_manifest_references_real_tests(self):
        self.assertGreaterEqual(len(P0_DOD_TESTS), 10)
        for requirement, references in P0_DOD_TESTS.items():
            self.assertTrue(references, requirement)
            for reference in references:
                module_name, class_name, method_name = reference.rsplit(".", 2)
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                self.assertTrue(hasattr(cls, method_name), reference)

    def test_declared_identity_graph_is_acyclic(self):
        assert_identity_graph_acyclic()

    def test_preexisting_backup_destination_is_not_deleted(self):
        destination = self.root / "existing-backup"
        destination.mkdir()
        sentinel = destination / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            backup(self.store, destination)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_verify_does_not_create_missing_empty_raw_directory(self):
        root = self.root / "readonly-verify"
        store = Store(root)
        store.close()
        (root / "raw").rmdir()
        verify(root)
        self.assertFalse((root / "raw").exists())

    def test_retention_policy_is_non_destructive_configuration(self):
        DEFAULT_BACKUP_RETENTION.validate()
        self.assertEqual(DEFAULT_BACKUP_RETENTION.daily, 30)
        self.assertEqual(DEFAULT_BACKUP_RETENTION.monthly, 12)
        self.assertTrue(DEFAULT_BACKUP_RETENTION.keep_pinned)
        with self.assertRaises(ValueError):
            BackupRetentionPolicy(daily=0).validate()


if __name__ == "__main__":
    unittest.main()
