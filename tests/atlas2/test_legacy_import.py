import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas2.core.enums import AvailabilityBasis
from atlas2.core.ids import make_id
from atlas2.core.taint import Taint
from atlas2.data.datasets import freeze_dataset, make_bar_fact
from atlas2.data.ingest import ingest_source_bytes
from atlas2.labels.select import LabelSelectionService
from atlas2.labels.tasks import LabelTaskService
from atlas2.legacy_import.checkpoint import checkpoint_file, sha256_file
from atlas2.legacy_import.h4_history import (
    import_records, inspect_source, read_records, validate_mapping,
)
from atlas2.model.data import FactLink
from atlas2.store.repository import Store, StoreConflict, ConflictKind

H4 = 4 * 60 * 60 * 1_000_000
CLOCK = make_id("comp", "clock-profile-v1", {"zone": "UTC"})
NORM = make_id("comp", "normalizer-v1", {"name": "legacy-test"})
SPEC = make_id("comp", "instrument-spec-v1", {"symbol": "EURUSD", "digits": 5})


def mapping():
    return {
        "table": "h4_history",
        "source_key": "legacy_id",
        "actor": "actor",
        "instrument": "symbol",
        "trend": "trend",
        "confidence": "confidence",
        "impulse_start_price": "start_price",
        "impulse_start_side": "start_side",
        "impulse_end_price": "end_price",
        "impulse_end_side": "end_side",
        "correction_price": "correction_price",
        "correction_side": "correction_side",
        "owner_values": ["OWNER"],
        "engine_values": ["ENGINE"],
        "trend_map": {"UP": "BULLISH", "DOWN": "BEARISH"},
        "price_mode": "SCALED_INT",
        "price_digits": 5,
        "market_price_side": "BID",
    }


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.legacy_db = root / "h4_impulse_history.sqlite3"
        conn = sqlite3.connect(self.legacy_db)
        conn.execute(
            """CREATE TABLE h4_history(
               legacy_id TEXT PRIMARY KEY,
               actor TEXT NOT NULL,
               symbol TEXT NOT NULL,
               trend TEXT NOT NULL,
               confidence INTEGER NOT NULL,
               start_price INTEGER NOT NULL,
               start_side TEXT NOT NULL,
               end_price INTEGER NOT NULL,
               end_side TEXT NOT NULL,
               correction_price INTEGER,
               correction_side TEXT
            )"""
        )
        conn.executemany(
            "INSERT INTO h4_history VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("owner-1", "OWNER", "EURUSD", "UP", 4, 90000, "LOW", 120000, "HIGH", None, None),
                ("engine-1", "ENGINE", "EURUSD", "DOWN", 3, 90000, "LOW", 120000, "HIGH", 95000, "LOW"),
            ],
        )
        conn.commit()
        conn.close()

        self.store = Store(root / "store")
        self.addCleanup(self.store.close)
        obs = ingest_source_bytes(
            self.store,
            b"legacy-import-market",
            source_id="synthetic",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=0,
            clock_profile_id=CLOCK,
        )
        bar = make_bar_fact(
            instrument_id="EURUSD",
            timeframe="H4",
            price_side="BID",
            open_time_us=0,
            close_time_us=H4,
            open=100000,
            high=120000,
            low=90000,
            close=110000,
            tick_volume=100,
            real_volume=None,
            spread_points=10,
            spread_semantics="LAST",
            instrument_spec_id=SPEC,
        )
        link = FactLink(
            bar.fact_id, obs.obs_id, "h4:0", NORM, H4,
            AvailabilityBasis.BAR_CLOSE_RULE, 0,
        )
        self.store.put_many([bar, link])
        self.dataset = freeze_dataset(
            self.store,
            [("BAR", bar.fact_id, link.obs_id, link.locator)],
            coverage={"instruments": ["EURUSD"], "start_us": 0, "end_us": H4 * 3},
            causal_policy={"bar_publication_lag_us": 0},
            htf_policy={"base": "M15", "alignment": "UTC"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=CLOCK,
            instrument_specs={"EURUSD": SPEC},
            tzdata_version="synthetic-v1",
            display_name="legacy-import-fixture",
            built_at_us=H4 * 4,
        )
        tasks = LabelTaskService(self.store)
        _, self.owner_task = tasks.create(
            study_id="legacy-owner",
            instrument_id="EURUSD",
            timeframe="H4",
            dataset_id=self.dataset.dataset_id,
            visible_data_cutoff_us=H4 * 2,
            lookback_bars=2,
            blind_mode="NONE",
            repeat_index=0,
            actor="ali",
            purpose="legacy-import",
        )
        _, self.engine_task = tasks.create(
            study_id="legacy-engine",
            instrument_id="EURUSD",
            timeframe="H4",
            dataset_id=self.dataset.dataset_id,
            visible_data_cutoff_us=H4 * 2,
            lookback_bars=2,
            blind_mode="NONE",
            repeat_index=0,
            actor="ali",
            purpose="legacy-import",
        )
        self.task_map = {
            "owner-1": self.owner_task.task_id,
            "engine-1": self.engine_task.task_id,
        }

    def test_read_only_source_hash_and_schema_checkpoint(self):
        before = sha256_file(self.legacy_db)
        source = inspect_source(self.legacy_db, mapping())
        self.assertEqual(source.source_sha256, before)
        self.assertEqual(sha256_file(self.legacy_db), before)
        self.assertEqual(checkpoint_file(self.legacy_db, before).status, "VERIFIED_HASH")
        self.assertEqual(checkpoint_file(Path(self.tmp.name) / "missing.db").status, "NOT_VERIFIED")

    def test_schema_mapping_fails_closed(self):
        bad = mapping()
        bad["confidence"] = "missing_column"
        with self.assertRaisesRegex(ValueError, "columns not present"):
            inspect_source(self.legacy_db, bad)
        bad = mapping()
        bad["table"] = "h4_history; DROP TABLE h4_history"
        with self.assertRaisesRegex(ValueError, "simple SQLite identifiers"):
            validate_mapping(bad)
        bad = mapping()
        bad["actor"] = bad["source_key"]
        with self.assertRaisesRegex(ValueError, "columns must be distinct"):
            validate_mapping(bad)
        bad = mapping()
        bad["market_price_side"] = "LAST"
        with self.assertRaisesRegex(ValueError, "BID/ASK/MID"):
            validate_mapping(bad)

    def test_null_required_legacy_text_fails_closed(self):
        conn = sqlite3.connect(self.legacy_db)
        conn.execute(
            """CREATE TABLE h4_history_nullable(
               legacy_id TEXT, actor TEXT, symbol TEXT, trend TEXT, confidence INTEGER,
               start_price INTEGER, start_side TEXT, end_price INTEGER, end_side TEXT,
               correction_price INTEGER, correction_side TEXT)"""
        )
        conn.execute(
            "INSERT INTO h4_history_nullable VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("null-actor", None, "EURUSD", "UP", 4, 90000, "LOW", 120000, "HIGH", None, None),
        )
        conn.commit(); conn.close()
        nullable_mapping = mapping()
        nullable_mapping["table"] = "h4_history_nullable"
        with self.assertRaisesRegex(ValueError, "actor cannot be NULL"):
            read_records(self.legacy_db, nullable_mapping)

    def test_versioned_sqlite_real_price_conversion_is_deterministic(self):
        conn = sqlite3.connect(self.legacy_db)
        conn.execute(
            """CREATE TABLE h4_history_real(
               legacy_id TEXT, actor TEXT, symbol TEXT, trend TEXT, confidence INTEGER,
               start_price REAL, start_side TEXT, end_price REAL, end_side TEXT,
               correction_price REAL, correction_side TEXT)"""
        )
        conn.execute(
            "INSERT INTO h4_history_real VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("real-1", "OWNER", "EURUSD", "UP", 4, 1.100005, "LOW", 1.100015, "HIGH", None, None),
        )
        conn.commit(); conn.close()
        real_mapping = mapping()
        real_mapping["table"] = "h4_history_real"
        real_mapping["price_mode"] = "SQLITE_REAL_DECIMAL_V1"
        _, records = read_records(self.legacy_db, real_mapping)
        anchors = {a["role"]: a["price"] for a in records[0].anchors}
        self.assertEqual(anchors["IMPULSE_START"], 110000)
        self.assertEqual(anchors["IMPULSE_END"], 110002)

    def test_owner_and_engine_rows_import_as_non_operational_evidence(self):
        result = import_records(
            self.store, self.legacy_db, mapping(),
            task_by_source_key=self.task_map,
            infer_unique_price_matches=False,
        )
        self.assertEqual(len(result.imported_group_ids), 2)
        rows = self.store.conn.execute(
            "SELECT labeler_id,label_mode,operational_available_at_us,taint "
            "FROM label_groups ORDER BY labeler_id"
        ).fetchall()
        by_labeler = {row["labeler_id"]: row for row in rows}
        self.assertEqual(by_labeler["legacy:owner"]["label_mode"], "LEGACY_IMPORT")
        self.assertEqual(by_labeler["legacy:engine"]["label_mode"], "ENGINE")
        self.assertIsNone(by_labeler["legacy:owner"]["operational_available_at_us"])
        self.assertIsNone(by_labeler["legacy:engine"]["operational_available_at_us"])
        self.assertTrue(by_labeler["legacy:owner"]["taint"] & int(Taint.INFERRED_RECONSTRUCTION))
        self.assertTrue(by_labeler["legacy:engine"]["taint"] & int(Taint.INFERRED_RECONSTRUCTION))
        statuses = {
            row[0] for row in self.store.conn.execute("SELECT time_status FROM label_anchors")
        }
        self.assertEqual(statuses, {"UNKNOWN_LEGACY"})

    def test_unique_price_match_is_only_an_inferred_reconstruction(self):
        import_records(
            self.store, self.legacy_db, mapping(),
            task_by_source_key=self.task_map,
            infer_unique_price_matches=True,
        )
        rows = self.store.conn.execute(
            """SELECT a.time_status,a.bar_open_time_us,g.labeler_id
               FROM label_anchors a
               JOIN label_interpretations i ON i.interpretation_id=a.interpretation_id
               JOIN label_groups g ON g.group_id=i.group_id
               ORDER BY g.labeler_id,a.role"""
        ).fetchall()
        self.assertIn(("INFERRED_RECONSTRUCTION", 0), {(r["time_status"], r["bar_open_time_us"]) for r in rows})
        owner = self.store.conn.execute(
            "SELECT taint FROM label_groups WHERE labeler_id='legacy:owner'"
        ).fetchone()[0]
        self.assertTrue(owner & int(Taint.INFERRED_RECONSTRUCTION))

    def test_import_retry_is_idempotent_and_source_unchanged(self):
        before = sha256_file(self.legacy_db)
        first = import_records(
            self.store, self.legacy_db, mapping(), task_by_source_key=self.task_map
        )
        counts_before = {
            table: self.store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("legacy_import_sources", "legacy_import_rows", "label_groups", "label_interpretations", "label_anchors")
        }
        second = import_records(
            self.store, self.legacy_db, mapping(), task_by_source_key=self.task_map
        )
        counts_after = {
            table: self.store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in counts_before
        }
        self.assertEqual(first.imported_group_ids, second.imported_group_ids)
        self.assertEqual(counts_before, counts_after)
        self.assertEqual(before, sha256_file(self.legacy_db))

    def test_changed_task_mapping_is_identity_conflict(self):
        import_records(
            self.store, self.legacy_db, mapping(), task_by_source_key=self.task_map
        )
        groups_before = self.store.conn.execute("SELECT count(*) FROM label_groups").fetchone()[0]
        changed = dict(self.task_map)
        changed["owner-1"] = self.engine_task.task_id
        with self.assertRaises(StoreConflict) as ctx:
            import_records(
                self.store, self.legacy_db, mapping(), task_by_source_key=changed
            )
        self.assertEqual(ctx.exception.kind, ConflictKind.IDENTITY_CONFLICT)
        self.assertEqual(
            groups_before,
            self.store.conn.execute("SELECT count(*) FROM label_groups").fetchone()[0],
        )

    def test_operational_view_cannot_see_legacy_or_engine_imports(self):
        import_records(
            self.store, self.legacy_db, mapping(), task_by_source_key=self.task_map
        )
        selector = LabelSelectionService(self.store)
        operational = selector.select(
            task_id=self.owner_task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=2_000_000_000_000_000,
            authorized_labelers=("legacy:owner",),
            selector_policy_version="per-labeler-latest-v1",
        )
        research = selector.select(
            task_id=self.owner_task.task_id,
            view_kind="RESEARCH",
            as_of_us=2_000_000_000_000_000,
            authorized_labelers=("legacy:owner",),
            selector_policy_version="per-labeler-latest-v1",
        )
        self.assertEqual(operational.group_ids, ())
        self.assertEqual(len(research.group_ids), 1)
        self.assertTrue(research.taint & int(Taint.INFERRED_RECONSTRUCTION))

    def test_source_record_inventory_is_deterministic(self):
        source_a, records_a = read_records(self.legacy_db, mapping())
        source_b, records_b = read_records(self.legacy_db, mapping())
        self.assertEqual(source_a, source_b)
        self.assertEqual(records_a, records_b)
        self.assertEqual([r.source_key for r in records_a], ["engine-1", "owner-1"])

    def test_legacy_tables_are_immutable(self):
        import_records(
            self.store, self.legacy_db, mapping(), task_by_source_key=self.task_map
        )
        source_id = self.store.conn.execute(
            "SELECT source_id FROM legacy_import_sources"
        ).fetchone()[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "IMMUTABLE_EVIDENCE"):
            self.store.conn.execute(
                "UPDATE legacy_import_sources SET basename=basename WHERE source_id=?",
                (source_id,),
            )


if __name__ == "__main__":
    unittest.main()
