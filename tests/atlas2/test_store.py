import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas2.store.db import connect
from atlas2.store.migrate import apply_migrations


class StoreTests(unittest.TestCase):
    def test_migrate_and_pragmas(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "atlas.sqlite3"
            apply_migrations(db)
            conn = connect(db)
            try:
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("run_manifests", names)
                self.assertIn("sys_request_keys", names)
            finally:
                conn.close()

    def test_evidence_rows_are_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "atlas.sqlite3"
            apply_migrations(db)
            conn = connect(db)
            try:
                conn.execute(
                    "INSERT INTO sys_request_keys(actor_id,action_kind,client_key,payload_digest,result_ref,server_time_us) VALUES (?,?,?,?,?,?)",
                    ("ali", "TEST", "k1", "0" * 64, "x", 1),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("UPDATE sys_request_keys SET result_ref='y' WHERE client_key='k1'")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("DELETE FROM sys_request_keys WHERE client_key='k1'")
            finally:
                conn.close()

    def test_holdout_session_is_pinned_in_manifest_schema(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "atlas.sqlite3"
            apply_migrations(db)
            conn = connect(db)
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(run_manifests)")}
                self.assertIn("holdout_batch_session_id", cols)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
