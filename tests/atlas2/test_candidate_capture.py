import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas2.core.enums import AvailabilityBasis
from atlas2.core.errors import CanonicalEncodingError
from atlas2.core.ids import make_id
from atlas2.data.datasets import freeze_dataset, make_bar_fact
from atlas2.data.ingest import ingest_source_bytes
from atlas2.detect.capture import CandidateCaptureService
from atlas2.model.candidates import make_occurrence_key
from atlas2.model.data import FactLink
from atlas2.store.backup import verify
from atlas2.store.records import RunManifest, RunAttemptStart
from atlas2.store.repository import ConflictKind, Store, StoreConflict

M15 = 15 * 60 * 1_000_000
CLOCK = make_id("comp", "clock-profile-v1", {"zone": "UTC"})
NORM = make_id("comp", "normalizer-v1", {"name": "test"})
SPEC = make_id("comp", "instrument-spec-v1", {"symbol": "EURUSD", "digits": 5})


class CandidateCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "store")
        self.addCleanup(self.store.close)

        obs = ingest_source_bytes(
            self.store,
            b"candidate-source",
            source_id="synthetic",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=0,
            clock_profile_id=CLOCK,
        )
        self.bar = make_bar_fact(
            instrument_id="EURUSD",
            timeframe="M15",
            price_side="BID",
            open_time_us=0,
            close_time_us=M15,
            open=100000,
            high=101000,
            low=99000,
            close=100500,
            tick_volume=20,
            real_volume=None,
            spread_points=12,
            spread_semantics="LAST",
            instrument_spec_id=SPEC,
        )
        link = FactLink(
            self.bar.fact_id,
            obs.obs_id,
            "row:1",
            NORM,
            M15,
            AvailabilityBasis.BAR_CLOSE_RULE,
            0,
        )
        self.store.put_many([self.bar, link])
        self.dataset = freeze_dataset(
            self.store,
            [("BAR", self.bar.fact_id, link.obs_id, link.locator)],
            coverage={"instruments": ["EURUSD"], "start_us": 0, "end_us": M15 * 4},
            causal_policy={"bar_publication_lag_us": 0},
            htf_policy={"base": "M15", "alignment": "UTC"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=CLOCK,
            instrument_specs={"EURUSD": SPEC},
            tzdata_version="synthetic-v1",
            display_name="candidate-fixture",
            built_at_us=M15 * 10,
        )

        self.manifest = RunManifest("manifest-candidate", "0" * 64, None, "REPLAY", "{}")
        self.attempt = RunAttemptStart(
            "attempt-candidate", self.manifest.manifest_id, 1, 1, M15, "{}"
        )
        self.store.put(self.manifest)
        self.store.put(self.attempt)
        self.capture = CandidateCaptureService(self.store)

    def invocation(self, *, detector_version="v1", detector_id="M15_CHANNEL"):
        return self.capture.start_invocation(
            run_attempt_id=self.attempt.attempt_id,
            dataset_id=self.dataset.dataset_id,
            detector_id=detector_id,
            detector_version=detector_version,
            instrument_id="EURUSD",
            timeframe="M15",
            as_of_us=M15 * 2,
            parameters={"lookback": 40},
        )

    def raw(
        self, invocation, *, index=1, available_at=M15, raw_payload=None,
        evidence_refs=None, anchors=None,
    ):
        return self.capture.record_raw(
            invocation_id=invocation.invocation_id,
            receipt_index=index,
            pattern_family="CHANNEL",
            direction="LONG",
            trigger_time_us=M15,
            detected_at_us=M15,
            available_at_us=available_at,
            anchors=anchors or [
                {"role": "channel_start", "time_us": 0},
                {"role": "breakout", "time_us": M15},
            ],
            raw_payload=raw_payload or {"status": "VALID_TRIGGER", "quality_ppm": 800_000},
            evidence_refs=evidence_refs or (self.bar.fact_id,),
            taint=0,
            actor="detector",
        )

    def candidate(self, raw, *, entry=100500, features=None):
        return self.capture.normalize_candidate(
            receipt_id=raw.receipt_id,
            entry_reference_price=entry,
            structural_invalidation_price=99000,
            features=features or {"channel_reactions": 4},
            confidence_ppm=800_000,
            actor="detector",
        )

    def test_candidate_first_path_and_completed_counts(self):
        inv = self.invocation()
        raw = self.raw(inv)
        self.assertEqual(
            self.store.conn.execute("SELECT count(*) FROM raw_detection_receipts").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.conn.execute("SELECT count(*) FROM candidates").fetchone()[0], 0
        )
        cand = self.candidate(raw)
        end = self.capture.end_invocation(inv.invocation_id, "COMPLETED")
        self.assertEqual((end.receipt_count, end.candidate_count), (1, 1))
        self.assertEqual(cand.receipt_id, raw.receipt_id)
        self.assertEqual(cand.occurrence_key, raw.occurrence_key)

    def test_raw_receipt_survives_candidate_normalization_failure(self):
        inv = self.invocation()
        raw = self.raw(inv)
        with self.assertRaises(CanonicalEncodingError):
            self.candidate(raw, features={"illegal_float": 1.25})
        self.assertEqual(
            self.store.conn.execute(
                "SELECT count(*) FROM raw_detection_receipts WHERE receipt_id=?",
                (raw.receipt_id,),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.conn.execute("SELECT count(*) FROM candidates").fetchone()[0], 0
        )
        end = self.capture.end_invocation(inv.invocation_id, "FAILED", error_code="NORMALIZE")
        self.assertEqual((end.receipt_count, end.candidate_count), (1, 0))

    def test_completed_requires_candidate_for_every_receipt(self):
        inv = self.invocation()
        raw = self.raw(inv)
        with self.assertRaisesRegex(ValueError, "one candidate"):
            self.capture.end_invocation(inv.invocation_id, "COMPLETED")
        self.assertEqual(
            self.store.conn.execute("SELECT count(*) FROM detector_invocation_ends").fetchone()[0],
            0,
        )
        self.candidate(raw)
        end = self.capture.end_invocation(inv.invocation_id, "COMPLETED")
        self.assertEqual(end.status, "COMPLETED")

    def test_raw_request_retry_and_changed_payload_conflict(self):
        inv = self.invocation()
        first = self.raw(inv)
        retry = self.raw(inv)
        self.assertEqual(first, retry)
        with self.assertRaises(StoreConflict) as ctx:
            self.raw(inv, raw_payload={"status": "VALID_TRIGGER", "quality_ppm": 700_000})
        self.assertEqual(ctx.exception.kind, ConflictKind.LOGICAL_KEY_CONFLICT)

    def test_candidate_retry_and_changed_normalization_conflict(self):
        inv = self.invocation()
        raw = self.raw(inv)
        first = self.candidate(raw)
        retry = self.candidate(raw)
        self.assertEqual(first, retry)
        with self.assertRaises(StoreConflict) as ctx:
            self.candidate(raw, entry=100600)
        self.assertEqual(ctx.exception.kind, ConflictKind.LOGICAL_KEY_CONFLICT)

    def test_occurrence_key_ignores_detector_version_and_prices(self):
        inv1 = self.invocation(detector_version="v1")
        raw1 = self.raw(inv1)
        cand1 = self.candidate(raw1, entry=100500)

        inv2 = self.invocation(detector_version="v2")
        raw2 = self.raw(inv2)
        cand2 = self.candidate(raw2, entry=100900)

        self.assertNotEqual(inv1.invocation_id, inv2.invocation_id)
        self.assertNotEqual(raw1.receipt_id, raw2.receipt_id)
        self.assertEqual(raw1.occurrence_key, raw2.occurrence_key)
        self.assertEqual(cand1.occurrence_key, cand2.occurrence_key)
        self.assertNotEqual(cand1.candidate_id, cand2.candidate_id)

    def test_evidence_refs_reject_text_input(self):
        inv = self.invocation()
        with self.assertRaisesRegex(ValueError, "ID collection"):
            self.capture.record_raw(
                invocation_id=inv.invocation_id, receipt_index=1,
                pattern_family="CHANNEL", direction="LONG",
                trigger_time_us=M15, detected_at_us=M15, available_at_us=M15,
                anchors=[{"role": "breakout", "time_us": M15}],
                raw_payload={"status": "VALID_TRIGGER"},
                evidence_refs=self.bar.fact_id, taint=0,
            )

    def test_occurrence_key_changes_with_causal_anchor_time(self):
        first = make_occurrence_key(
            instrument_id="EURUSD",
            timeframe="M15",
            pattern_family="CHANNEL",
            direction="LONG",
            trigger_time_us=M15,
            anchors=[{"role": "breakout", "time_us": M15}],
        )
        second = make_occurrence_key(
            instrument_id="EURUSD",
            timeframe="M15",
            pattern_family="CHANNEL",
            direction="LONG",
            trigger_time_us=M15,
            anchors=[{"role": "breakout", "time_us": M15 + 1}],
        )
        self.assertNotEqual(first, second)

    def test_receipt_rejects_future_occurrence_anchor(self):
        inv = self.invocation()
        with self.assertRaisesRegex(ValueError, "anchor is after detection"):
            self.raw(
                inv,
                anchors=[
                    {"role": "channel_start", "time_us": 0},
                    {"role": "future", "time_us": M15 + 1},
                ],
            )
        self.assertEqual(
            self.store.conn.execute("SELECT count(*) FROM raw_detection_receipts").fetchone()[0],
            0,
        )

    def test_receipt_evidence_must_belong_to_invocation_dataset(self):
        inv = self.invocation()
        other = make_bar_fact(
            instrument_id="EURUSD", timeframe="M15", price_side="BID",
            open_time_us=M15, close_time_us=M15 * 2,
            open=100500, high=101500, low=99500, close=101000,
            tick_volume=20, real_volume=None, spread_points=12,
            spread_semantics="LAST", instrument_spec_id=SPEC,
        )
        self.store.put(other)
        with self.assertRaisesRegex(ValueError, "not in invocation dataset"):
            self.raw(inv, evidence_refs=(other.fact_id,))

    def test_receipt_cannot_see_after_invocation_asof(self):
        inv = self.invocation()
        with self.assertRaisesRegex(ValueError, "as_of"):
            self.raw(inv, available_at=M15 * 2 + 1)
        self.assertEqual(
            self.store.conn.execute("SELECT count(*) FROM raw_detection_receipts").fetchone()[0],
            0,
        )

    def test_terminal_invocation_rejects_new_receipts_and_candidates(self):
        inv = self.invocation()
        raw = self.raw(inv)
        self.candidate(raw)
        self.capture.end_invocation(inv.invocation_id, "COMPLETED")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "DETECTOR_INVOCATION_TERMINAL"):
            self.capture.record_raw(
                invocation_id=inv.invocation_id,
                receipt_index=2,
                pattern_family="FLAG",
                direction="LONG",
                trigger_time_us=M15,
                detected_at_us=M15,
                available_at_us=M15,
                anchors=[{"role": "breakout", "time_us": M15}],
                raw_payload={"status": "VALID_TRIGGER"},
                evidence_refs=(self.bar.fact_id,),
                taint=0,
            )

    def test_raw_sql_receipt_must_match_invocation_identity(self):
        inv = self.invocation()
        occurrence = make_occurrence_key(
            instrument_id="EURUSD", timeframe="M15", pattern_family="CHANNEL",
            direction="LONG", trigger_time_us=M15,
            anchors=[{"role": "breakout", "time_us": M15}],
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "DETECTION_INVOCATION_MISMATCH_OR_ASOF"):
            self.store.conn.execute(
                """INSERT INTO raw_detection_receipts VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "rdet_" + "4" * 64, inv.invocation_id, 99, occurrence,
                    "EURUSD", "M15", "CHANNEL", "LONG", M15, M15, M15,
                    '[{"role":"breakout","time_us":900000000}]',
                    '{"status":"VALID_TRIGGER"}',
                    '["%s"]' % self.bar.fact_id,
                    "M15_CHANNEL", "WRONG_VERSION", 0, M15,
                ),
            )

    def test_raw_sql_candidate_must_match_receipt(self):
        inv = self.invocation()
        raw = self.raw(inv)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CANDIDATE_RECEIPT_MISMATCH"):
            self.store.conn.execute(
                """INSERT INTO candidates VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "cand_" + "0" * 64,
                    raw.receipt_id,
                    raw.occurrence_key,
                    raw.instrument_id,
                    raw.timeframe,
                    raw.pattern_family,
                    "SHORT",
                    raw.trigger_time_us,
                    raw.detected_at_us,
                    raw.available_at_us,
                    100500,
                    99000,
                    "{}",
                    None,
                    raw.evidence_refs_json,
                    raw.source_detector_id,
                    raw.source_detector_version,
                    raw.taint,
                    raw.recorded_at_us + 1,
                ),
            )

    def test_schema_immutability_and_verification(self):
        inv = self.invocation()
        raw = self.raw(inv)
        cand = self.candidate(raw)
        self.capture.end_invocation(inv.invocation_id, "COMPLETED")
        verify(self.store.root)
        for table in (
            "detector_invocations",
            "raw_detection_receipts",
            "candidates",
            "detector_invocation_ends",
        ):
            column = self.store.conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchone()["name"]
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.conn.execute(f"UPDATE {table} SET {column}={column}")
        self.assertEqual(
            self.store.conn.execute(
                "SELECT candidate_id FROM candidates WHERE receipt_id=?", (raw.receipt_id,)
            ).fetchone()[0],
            cand.candidate_id,
        )

    def test_detect_module_has_no_downstream_or_legacy_imports(self):
        text = (Path(__file__).parents[2] / "atlas2" / "detect" / "capture.py").read_text()
        forbidden = (
            "atlas2.evaluate",
            "atlas2.execution",
            "atlas.execution",
            "atlas.supervisor",
            "news_guard",
            "risk.policy",
        )
        for token in forbidden:
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
