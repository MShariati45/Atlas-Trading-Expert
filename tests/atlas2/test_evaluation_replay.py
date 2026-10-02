import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas2.core.canonical import canonical_json_text
from atlas2.core.enums import AvailabilityBasis, DataQualityFlag
from atlas2.core.ids import make_id
from atlas2.core.taint import Taint
from atlas2.data.datasets import freeze_dataset, make_bar_fact
from atlas2.data.ingest import ingest_source_bytes
from atlas2.detect.capture import CandidateCaptureService
from atlas2.evaluate.context import build_snapshot, create_context, seal_capture_unit
from atlas2.evaluate.ledger import evaluate_c0, persist_fixture_outcome_batch
from atlas2.evaluate.p1_track_a import evaluate_p1_track_a
from atlas2.evaluate.relations import add_relation
from atlas2.model.data import FactLink
from atlas2.model.evaluation import GateResult, OutcomeBatch
from atlas2.model.labels import (
    Interpretation,
    LabelSetPin,
    LabelSubmissionGroup,
    LabelTask,
    LabelTaskSeed,
)
from atlas2.replay.digest import confirm_aggregate, replay_digest_for_store
from atlas2.replay.projection import project_context
from atlas2.shadow.report import build_shadow_report, render_shadow_report_json
from atlas2.store.records import RunManifest, RunAttemptStart
from atlas2.store.repository import ConflictKind, Store, StoreConflict

M15 = 15 * 60 * 1_000_000
CLOCK = make_id("comp", "clock-profile-v1", {"zone": "UTC"})
NORM = make_id("comp", "normalizer-v1", {"name": "eval-test"})
SPEC = make_id("comp", "instrument-spec-v1", {"symbol": "EURUSD", "digits": 5})


class Fixture:
    def __init__(
        self, root: Path, *, attempt_id="attempt-eval", extra_availability=None,
        base_quality_flags=0, source_acquired_at=0,
    ):
        self.store = Store(root)
        self.obs = ingest_source_bytes(
            self.store,
            b"eval-source",
            source_id="synthetic",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=source_acquired_at,
            clock_profile_id=CLOCK,
        )
        self.base_bar = make_bar_fact(
            instrument_id="EURUSD", timeframe="M15", price_side="BID",
            open_time_us=0, close_time_us=M15,
            open=100000, high=101000, low=99000, close=100500,
            tick_volume=20, real_volume=None, spread_points=12,
            spread_semantics="LAST", instrument_spec_id=SPEC,
        )
        base_link = FactLink(
            self.base_bar.fact_id, self.obs.obs_id, "base", NORM, M15,
            AvailabilityBasis.BAR_CLOSE_RULE, base_quality_flags,
        )
        self.store.put_many([self.base_bar, base_link])
        memberships = [("BAR", self.base_bar.fact_id, base_link.obs_id, base_link.locator)]

        self.extra_bar = None
        if extra_availability is not None:
            self.extra_bar = make_bar_fact(
                instrument_id="EURUSD", timeframe="M15", price_side="BID",
                open_time_us=0, close_time_us=M15,
                open=100000, high=101100, low=98900, close=100600,
                tick_volume=21, real_volume=None, spread_points=12,
                spread_semantics="LAST", instrument_spec_id=SPEC,
            )
            extra_link = FactLink(
                self.extra_bar.fact_id, self.obs.obs_id, "revision", NORM,
                extra_availability, AvailabilityBasis.SOURCE_STAMPED, 0,
            )
            self.store.put_many([self.extra_bar, extra_link])
            memberships.append(
                ("BAR", self.extra_bar.fact_id, extra_link.obs_id, extra_link.locator)
            )

        self.dataset = freeze_dataset(
            self.store,
            memberships,
            coverage={"instruments": ["EURUSD"], "start_us": 0, "end_us": M15 * 4},
            causal_policy={"bar_publication_lag_us": 0},
            htf_policy={"base": "M15", "alignment": "UTC"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=CLOCK,
            instrument_specs={"EURUSD": SPEC},
            tzdata_version="synthetic-v1",
            display_name="eval-fixture",
            built_at_us=M15 * 10,
        )
        self.manifest = RunManifest("manifest-eval", "1" * 64, None, "REPLAY", "{}")
        self.attempt = RunAttemptStart(
            attempt_id, self.manifest.manifest_id, 1, 1, M15, "{}"
        )
        self.store.put(self.manifest)
        self.store.put(self.attempt)
        capture = CandidateCaptureService(self.store)
        self.invocation = capture.start_invocation(
            run_attempt_id=self.attempt.attempt_id,
            dataset_id=self.dataset.dataset_id,
            detector_id="M15_CHANNEL",
            detector_version="v1",
            instrument_id="EURUSD",
            timeframe="M15",
            as_of_us=M15 * 2,
            parameters={"lookback": 40},
        )
        self.receipt = capture.record_raw(
            invocation_id=self.invocation.invocation_id,
            receipt_index=1,
            pattern_family="CHANNEL",
            direction="LONG",
            trigger_time_us=M15,
            detected_at_us=M15,
            available_at_us=M15,
            anchors=[
                {"role": "channel_start", "time_us": 0},
                {"role": "breakout", "time_us": M15},
            ],
            raw_payload={"status": "VALID_TRIGGER", "quality_ppm": 800_000},
            evidence_refs=(self.base_bar.fact_id,),
            taint=0,
        )
        self.candidate = capture.normalize_candidate(
            receipt_id=self.receipt.receipt_id,
            entry_reference_price=100500,
            structural_invalidation_price=99000,
            features={"channel_reactions": 4},
            confidence_ppm=800_000,
        )
        capture.end_invocation(self.invocation.invocation_id, "COMPLETED")
        self.snapshot = build_snapshot(
            self.store,
            dataset_id=self.dataset.dataset_id,
            instrument_id="EURUSD",
            as_of_us=M15 * 2,
            windows=[{
                "timeframe": "M15",
                "lookback": 2,
                "price_side": "BID",
                "include_partial": False,
            }],
        )
        self.capture_unit = seal_capture_unit(
            self.store,
            dataset_id=self.dataset.dataset_id,
            instrument_id="EURUSD",
            decision_time_us=M15 * 2,
            snapshot_id=self.snapshot.snapshot_id,
        )

    def evaluate(self, label_pin_id=None):
        ctx = create_context(
            self.store,
            capture_unit_id=self.capture_unit.capture_unit_id,
            label_pin_id=label_pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        arms = evaluate_c0(self.store, ctx_id=ctx.ctx_id)
        confirm_aggregate(
            self.store, self.manifest.manifest_id,
            "capture_units", self.capture_unit.capture_unit_id,
        )
        confirm_aggregate(
            self.store, self.manifest.manifest_id,
            "evaluation_contexts", ctx.ctx_id,
        )
        return ctx, arms


class EvaluationReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(Path(self.tmp.name) / "store")
        self.addCleanup(self.fx.store.close)

    def _seed_h4_correction_pin(
        self,
        *,
        depth_ppm=382_000,
        submitted_offset_us=0,
        seal_group=True,
        pin_view_kind="OPERATIONAL",
        study_id="p1-correction-location",
        labeler_id="ali",
        request_key="p1-correction-location-v1",
    ):
        cutoff = self.fx.capture_unit.decision_time_us
        seed = LabelTaskSeed.create(
            study_id,
            "EURUSD",
            "H4",
            self.fx.dataset.dataset_id,
            cutoff,
            1,
            "NONE",
            0,
        )
        task = LabelTask.create(seed.seed_id, {})
        group = LabelSubmissionGroup.create(
            task_id=task.task_id,
            labeler_id=labeler_id,
            request_key=request_key,
            kind="INTERPRETATIONS",
            label_mode="OPERATIONAL",
            submitted_at_us=cutoff + submitted_offset_us,
            visible_data_cutoff_us=cutoff,
            supersedes_group_id=None,
            revision_reason=None,
            abstention_reason=None,
            exposure_attestation="DECLARED",
            system_exposure_flag=False,
        )
        interpretation = Interpretation.create(
            group_id=group.group_id,
            rank=1,
            probability_ppm=1_000_000,
            trend="BULLISH",
            confidence=4,
            correction_depth_ppm=depth_ppm,
            correction_class="MINOR",
            reason="p1 correction measurement fixture",
        )
        pin = LabelSetPin.create(
            view_kind=pin_view_kind,
            group_ids=(group.group_id,),
            selector_policy_version="latest-authorized-owner-v1",
            taint=group.taint,
        )
        with self.fx.store.transaction():
            self.fx.store.conn.execute(
                "INSERT INTO label_task_seeds VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    seed.seed_id,
                    seed.study_id,
                    seed.instrument_id,
                    seed.timeframe,
                    seed.dataset_id,
                    seed.visible_data_cutoff_us,
                    seed.lookback_bars,
                    seed.blind_mode,
                    seed.repeat_index,
                    0,
                ),
            )
            self.fx.store.conn.execute(
                "INSERT INTO label_tasks VALUES (?,?,?)",
                (task.task_id, task.seed_id, task.transform_json),
            )
            self.fx.store.conn.execute(
                """INSERT INTO label_groups VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    group.group_id,
                    group.task_id,
                    group.labeler_id,
                    group.request_key,
                    group.kind,
                    group.label_mode,
                    group.submitted_at_us,
                    group.visible_data_cutoff_us,
                    group.operational_available_at_us,
                    group.supersedes_group_id,
                    group.revision_reason,
                    group.abstention_reason,
                    group.exposure_attestation,
                    int(group.system_exposure_flag),
                    group.taint,
                ),
            )
            self.fx.store.conn.execute(
                "INSERT INTO label_interpretations VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    interpretation.interpretation_id,
                    interpretation.group_id,
                    interpretation.rank,
                    interpretation.probability_ppm,
                    interpretation.trend,
                    interpretation.confidence,
                    interpretation.correction_depth_ppm,
                    interpretation.correction_class,
                    interpretation.reason,
                ),
            )
            if seal_group:
                self.fx.store.seal_current_transaction(
                    "label_groups", group.group_id
                )
            self.fx.store.conn.execute(
                "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
                (
                    pin.pin_id,
                    pin.view_kind,
                    canonical_json_text(list(pin.group_ids)),
                    pin.selector_policy_version,
                    pin.taint,
                ),
            )
        return pin, group

    def test_c0_evaluates_every_candidate_and_seals_unit(self):
        ctx, arms = self.fx.evaluate()
        self.assertEqual(len(arms), 1)
        self.assertEqual(arms[0].decision, "ACCEPT")
        gate = self.fx.store.conn.execute(
            "SELECT * FROM gate_results WHERE ctx_id=?", (ctx.ctx_id,)
        ).fetchone()
        self.assertEqual((gate["gate_kind"], gate["outcome"]), ("DATA_QUALITY", "PASS"))
        self.assertTrue(self.fx.store.conn.execute(
            "SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=?",
            (ctx.ctx_id,),
        ).fetchone())
        self.assertEqual(
            self.fx.store.conn.execute(
                "SELECT count(*) FROM arm_results WHERE ctx_id=? AND candidate_id=?",
                (ctx.ctx_id, self.fx.candidate.candidate_id),
            ).fetchone()[0],
            1,
        )

    def test_retry_writes_zero_new_evidence_rows(self):
        ctx, _ = self.fx.evaluate()
        tables = [
            "market_snapshots", "capture_units", "capture_unit_members",
            "evaluation_contexts", "gate_results", "arm_results",
            "evaluation_unit_members", "sys_seals",
        ]
        before = {
            table: self.fx.store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        same_capture = seal_capture_unit(
            self.fx.store,
            dataset_id=self.fx.dataset.dataset_id,
            instrument_id="EURUSD",
            decision_time_us=M15 * 2,
            snapshot_id=self.fx.snapshot.snapshot_id,
        )
        same_ctx = create_context(
            self.fx.store,
            capture_unit_id=same_capture.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_c0(self.fx.store, ctx_id=same_ctx.ctx_id)
        after = {
            table: self.fx.store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        self.assertEqual(ctx.ctx_id, same_ctx.ctx_id)
        self.assertEqual(before, after)

    def test_fresh_store_different_attempt_has_same_replay_digest(self):
        self.fx.evaluate()
        first = replay_digest_for_store(self.fx.store, self.fx.manifest.manifest_id)
        other_root = Path(self.tmp.name) / "second"
        second = Fixture(other_root, attempt_id="attempt-eval-second")
        self.addCleanup(second.store.close)
        second.evaluate()
        self.assertEqual(first, replay_digest_for_store(second.store, second.manifest.manifest_id))
        self.assertNotEqual(self.fx.candidate.candidate_id, second.candidate.candidate_id)
        self.assertEqual(
            self.fx.capture_unit.capture_unit_id, second.capture_unit.capture_unit_id
        )

    def test_manifest_scoped_digest_ignores_unconfirmed_aggregate(self):
        ctx, _ = self.fx.evaluate()
        before = replay_digest_for_store(self.fx.store, self.fx.manifest.manifest_id)
        pin = LabelSetPin.create(
            view_kind="RESEARCH", group_ids=(),
            selector_policy_version="per-labeler-latest-v1", taint=0,
        )
        self.fx.store.conn.execute(
            "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
            (pin.pin_id, pin.view_kind, canonical_json_text([]), pin.selector_policy_version, 0),
        )
        other = create_context(
            self.fx.store, capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id, macro_view_class="PIT", mode="REPLAY",
        )
        evaluate_c0(self.fx.store, ctx_id=other.ctx_id)
        self.assertNotEqual(ctx.ctx_id, other.ctx_id)
        self.assertEqual(before, replay_digest_for_store(self.fx.store, self.fx.manifest.manifest_id))

    def test_unknown_manifest_digest_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown run manifest"):
            replay_digest_for_store(self.fx.store, "missing-manifest")

    def test_crash_resume_digest_equals_uninterrupted_run(self):
        ctx = create_context(
            self.fx.store, capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=None, macro_view_class="PIT", mode="REPLAY",
        )
        with self.assertRaisesRegex(RuntimeError, "P0_7_INJECTED_GATE_FAULT"):
            evaluate_c0(self.fx.store, ctx_id=ctx.ctx_id, fault_after_first_gate=True)
        evaluate_c0(self.fx.store, ctx_id=ctx.ctx_id)
        confirm_aggregate(
            self.fx.store, self.fx.manifest.manifest_id,
            "capture_units", self.fx.capture_unit.capture_unit_id,
        )
        confirm_aggregate(
            self.fx.store, self.fx.manifest.manifest_id,
            "evaluation_contexts", ctx.ctx_id,
        )
        resumed = replay_digest_for_store(self.fx.store, self.fx.manifest.manifest_id)

        other = Fixture(Path(self.tmp.name) / "uninterrupted", attempt_id="attempt-uninterrupted")
        self.addCleanup(other.store.close)
        other.evaluate()
        uninterrupted = replay_digest_for_store(other.store, other.manifest.manifest_id)
        self.assertEqual(resumed, uninterrupted)

    def test_snapshot_windows_are_canonically_sorted(self):
        snapshot = build_snapshot(
            self.fx.store, dataset_id=self.fx.dataset.dataset_id,
            instrument_id="EURUSD", as_of_us=M15 * 2,
            windows=[
                {"timeframe": "M15", "lookback": 2, "price_side": "BID", "include_partial": False},
                {"timeframe": "M15", "lookback": 1, "price_side": "BID", "include_partial": False},
            ],
        )
        windows = __import__("json").loads(snapshot.windows_json)
        encoded = [canonical_json_text(window) for window in windows]
        self.assertEqual(encoded, sorted(encoded))

    def test_changed_label_pin_creates_new_context(self):
        first, _ = self.fx.evaluate()
        pin = LabelSetPin.create(
            view_kind="RESEARCH",
            group_ids=(),
            selector_policy_version="per-labeler-latest-v1",
            taint=int(Taint.RETRO_LABEL),
        )
        self.fx.store.conn.execute(
            "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
            (
                pin.pin_id,
                pin.view_kind,
                canonical_json_text(list(pin.group_ids)),
                pin.selector_policy_version,
                pin.taint,
            ),
        )
        second = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_c0(self.fx.store, ctx_id=second.ctx_id)
        self.assertNotEqual(first.ctx_id, second.ctx_id)
        self.assertTrue(second.taint & int(Taint.RETRO_LABEL))

    def test_gate_fault_rolls_back_evaluation_not_capture_and_resume_works(self):
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        with self.assertRaisesRegex(RuntimeError, "P0_7_INJECTED_GATE_FAULT"):
            evaluate_c0(
                self.fx.store, ctx_id=ctx.ctx_id, fault_after_first_gate=True
            )
        self.assertEqual(
            self.fx.store.conn.execute(
                "SELECT count(*) FROM gate_results WHERE ctx_id=?", (ctx.ctx_id,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.fx.store.conn.execute("SELECT count(*) FROM candidates").fetchone()[0],
            1,
        )
        arms = evaluate_c0(self.fx.store, ctx_id=ctx.ctx_id)
        self.assertEqual(len(arms), 1)
        self.assertTrue(self.fx.store.conn.execute(
            "SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=?",
            (ctx.ctx_id,),
        ).fetchone())

    def test_forward_invisible_evidence_abstains_without_aborting_context(self):
        root = Path(self.tmp.name) / "forward-invisible"
        fx = Fixture(root, source_acquired_at=M15 * 3)
        self.addCleanup(fx.store.close)
        forward_snapshot = build_snapshot(
            fx.store, dataset_id=fx.dataset.dataset_id, instrument_id="EURUSD",
            as_of_us=M15 * 2,
            windows=[{
                "timeframe": "M15", "lookback": 2, "price_side": "BID",
                "include_partial": False,
            }],
            mode="FORWARD",
        )
        forward_capture = seal_capture_unit(
            fx.store, dataset_id=fx.dataset.dataset_id, instrument_id="EURUSD",
            decision_time_us=M15 * 2, snapshot_id=forward_snapshot.snapshot_id,
        )
        ctx = create_context(
            fx.store, capture_unit_id=forward_capture.capture_unit_id,
            label_pin_id=None, macro_view_class="PIT", mode="FORWARD",
        )
        arms = evaluate_c0(fx.store, ctx_id=ctx.ctx_id)
        self.assertEqual(len(arms), 1)
        self.assertEqual(arms[0].decision, "ABSTAIN")
        gate = fx.store.conn.execute(
            "SELECT outcome,reason_code FROM gate_results WHERE ctx_id=?", (ctx.ctx_id,)
        ).fetchone()
        self.assertEqual((gate["outcome"], gate["reason_code"]), ("NOT_EVALUABLE", "EVIDENCE_NOT_VISIBLE"))
        self.assertTrue(fx.store.conn.execute(
            "SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=?",
            (ctx.ctx_id,),
        ).fetchone())

    def test_context_mode_must_match_snapshot_mode(self):
        with self.assertRaisesRegex(ValueError, "snapshot mode"):
            create_context(
                self.fx.store,
                capture_unit_id=self.fx.capture_unit.capture_unit_id,
                label_pin_id=None, macro_view_class="PIT", mode="FORWARD",
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CONTEXT_SNAPSHOT_MODE_MISMATCH"):
            self.fx.store.conn.execute(
                "INSERT INTO evaluation_contexts VALUES (?,?,?,?,?,?)",
                (
                    "ctx_" + "9" * 64, self.fx.capture_unit.capture_unit_id,
                    None, "PIT", "FORWARD", 0,
                ),
            )

    def test_data_quality_flag_rejects_c0(self):
        root = Path(self.tmp.name) / "flagged"
        fx = Fixture(root, base_quality_flags=int(DataQualityFlag.GAP))
        self.addCleanup(fx.store.close)
        ctx, arms = fx.evaluate()
        self.assertEqual(arms[0].decision, "REJECT")
        gate = fx.store.conn.execute(
            "SELECT * FROM gate_results WHERE ctx_id=?", (ctx.ctx_id,)
        ).fetchone()
        self.assertEqual(gate["outcome"], "FAIL")
        self.assertEqual(gate["reason_code"], "DATA_QUALITY_FLAGGED")

    def test_relation_is_directed_and_seal_blocks_late_relation(self):
        # Add a second detector version with the same occurrence so two peers exist.
        capture = CandidateCaptureService(self.fx.store)
        inv = capture.start_invocation(
            run_attempt_id=self.fx.attempt.attempt_id,
            dataset_id=self.fx.dataset.dataset_id,
            detector_id="M15_REVERSAL",
            detector_version="v1",
            instrument_id="EURUSD",
            timeframe="M15",
            as_of_us=M15 * 2,
            parameters={"lookback": 20},
        )
        raw = capture.record_raw(
            invocation_id=inv.invocation_id,
            receipt_index=1,
            pattern_family="REVERSAL",
            direction="LONG",
            trigger_time_us=M15,
            detected_at_us=M15,
            available_at_us=M15,
            anchors=[{"role": "breakout", "time_us": M15}],
            raw_payload={"status": "VALID_TRIGGER"},
            evidence_refs=(self.fx.base_bar.fact_id,),
            taint=0,
        )
        other = capture.normalize_candidate(
            receipt_id=raw.receipt_id,
            entry_reference_price=100550,
            structural_invalidation_price=99000,
            features={"reversal": 1},
            confidence_ppm=700_000,
        )
        capture.end_invocation(inv.invocation_id, "COMPLETED")
        # Existing capture unit was sealed before this new invocation; create a new semantic unit.
        snapshot = self.fx.snapshot
        unit = seal_capture_unit(
            self.fx.store,
            dataset_id=self.fx.dataset.dataset_id,
            instrument_id="EURUSD",
            decision_time_us=M15 * 2,
            snapshot_id=snapshot.snapshot_id,
        )
        ctx = create_context(
            self.fx.store,
            capture_unit_id=unit.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        rel = add_relation(
            self.fx.store,
            ctx_id=ctx.ctx_id,
            relation_kind="CONFIRMS",
            evaluator_version_id="relation-v1",
            primary_candidate_id=self.fx.candidate.candidate_id,
            other_candidate_id=other.candidate_id,
        )
        self.assertEqual(rel.primary_candidate_id, self.fx.candidate.candidate_id)
        reverse_id = make_id("rel", "candidate-relation-v1", {
            "ctx_id": ctx.ctx_id, "relation_kind": "CONFIRMS",
            "evaluator_version_id": "relation-v1",
            "primary_candidate_id": other.candidate_id,
            "other_candidate_id": self.fx.candidate.candidate_id,
        })
        self.assertNotEqual(rel.relation_id, reverse_id)
        evaluate_c0(self.fx.store, ctx_id=ctx.ctx_id)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "SEAL_VIOLATION"):
            self.fx.store.conn.execute(
                "INSERT INTO candidate_relations VALUES (?,?,?,?,?,?,?)",
                (
                    "rel_" + "f" * 64, ctx.ctx_id, "CONFIRMS", "late-v1",
                    other.candidate_id, self.fx.candidate.candidate_id, 0,
                ),
            )

    def test_correction_location_cannot_be_entry_gate(self):
        with self.assertRaisesRegex(ValueError, "measurement-only"):
            GateResult.create(
                ctx_id="ctx_" + "1" * 64,
                candidate_id="cand_" + "2" * 64,
                gate_kind="CORRECTION_LOCATION",
                evaluator_version_id="fib-measure-v1",
                input_refs=[],
                outcome="PASS",
                reason_code=None,
                error_code=None,
                measurements=[],
                taint=0,
            )

    def test_unfinished_context_cannot_be_sealed(self):
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "EVALUATION_UNIT_INCOMPLETE"):
            self.fx.store.seal("evaluation_contexts", ctx.ctx_id)

    def test_evaluation_rows_are_immutable(self):
        ctx, _ = self.fx.evaluate()
        gate_id = self.fx.store.conn.execute(
            "SELECT gate_id FROM gate_results WHERE ctx_id=?", (ctx.ctx_id,)
        ).fetchone()[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "IMMUTABLE_EVIDENCE"):
            self.fx.store.conn.execute(
                "UPDATE gate_results SET outcome=outcome WHERE gate_id=?", (gate_id,)
            )

    def test_capture_unit_cannot_seal_with_incomplete_members(self):
        fake_id = "capu_" + "a" * 64
        self.fx.store.conn.execute(
            "INSERT INTO capture_units VALUES (?,?,?,?,?,?,?)",
            (
                fake_id, self.fx.dataset.dataset_id, "EURUSD", M15 * 2,
                self.fx.snapshot.snapshot_id,
                canonical_json_text([self.fx.candidate.candidate_id]),
                "b" * 64,
            ),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (fake_id, "SNAPSHOT", self.fx.snapshot.snapshot_id, "c" * 64),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CAPTURE_UNIT_INCOMPLETE"):
            self.fx.store.seal("capture_units", fake_id)

    def test_capture_seal_requires_candidate_receipt_and_receipt_invocation_links(self):
        candidate_only = "capu_" + "d" * 64
        self.fx.store.conn.execute(
            "INSERT INTO capture_units VALUES (?,?,?,?,?,?,?)",
            (
                candidate_only, self.fx.dataset.dataset_id, "EURUSD", M15 * 2,
                self.fx.snapshot.snapshot_id,
                canonical_json_text([self.fx.candidate.candidate_id]),
                "e" * 64,
            ),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (candidate_only, "SNAPSHOT", self.fx.snapshot.snapshot_id, "1" * 64),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (candidate_only, "CANDIDATE", self.fx.candidate.candidate_id, "2" * 64),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CAPTURE_UNIT_INCOMPLETE"):
            self.fx.store.seal("capture_units", candidate_only)

        receipt_only = "capu_" + "e" * 64
        self.fx.store.conn.execute(
            "INSERT INTO capture_units VALUES (?,?,?,?,?,?,?)",
            (
                receipt_only, self.fx.dataset.dataset_id, "EURUSD", M15 * 2,
                self.fx.snapshot.snapshot_id, canonical_json_text([]), "f" * 64,
            ),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (receipt_only, "SNAPSHOT", self.fx.snapshot.snapshot_id, "3" * 64),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (receipt_only, "RECEIPT", self.fx.receipt.receipt_id, "4" * 64),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CAPTURE_UNIT_INCOMPLETE"):
            self.fx.store.seal("capture_units", receipt_only)

    def test_capture_seal_rejects_invocation_pair_missing_existing_receipt(self):
        fake_id = "capu_" + "6" * 64
        self.fx.store.conn.execute(
            "INSERT INTO capture_units VALUES (?,?,?,?,?,?,?)",
            (
                fake_id, self.fx.dataset.dataset_id, "EURUSD", M15 * 2,
                self.fx.snapshot.snapshot_id, canonical_json_text([]), "7" * 64,
            ),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (fake_id, "SNAPSHOT", self.fx.snapshot.snapshot_id, "8" * 64),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (fake_id, "INVOCATION", self.fx.invocation.invocation_id, "9" * 64),
        )
        self.fx.store.conn.execute(
            "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
            (fake_id, "INVOCATION_END", self.fx.invocation.invocation_id, "a" * 64),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CAPTURE_UNIT_INCOMPLETE"):
            self.fx.store.seal("capture_units", fake_id)

    def test_outcome_subject_must_match_batch_dataset(self):
        _, arms = self.fx.evaluate()
        other_dataset = freeze_dataset(
            self.fx.store,
            [("BAR", self.fx.base_bar.fact_id, self.fx.obs.obs_id, "base")],
            coverage={"instruments": ["EURUSD"], "start_us": 0, "end_us": M15 * 4},
            causal_policy={"bar_publication_lag_us": 1},
            htf_policy={"base": "M15", "alignment": "UTC"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=CLOCK, instrument_specs={"EURUSD": SPEC},
            tzdata_version="synthetic-v1", display_name="other-dataset",
            built_at_us=M15 * 11,
        )
        with self.assertRaisesRegex(ValueError, "dataset mismatch"):
            persist_fixture_outcome_batch(
                self.fx.store, dataset_id=other_dataset.dataset_id,
                fixture_name="cross-dataset",
                attachments=[{
                    "subject_kind": "ARM", "subject_ref": arms[0].arm_id,
                    "reference_plan_id": None, "resolver_version_id": "fixture-resolver-v1",
                    "cost_model_version_id": "fixture-cost-v1", "status": "RESOLVED",
                    "entry_time_us": M15 * 2, "r_low_micro": 0, "r_high_micro": 0,
                    "exit_reason": "FIXTURE", "be_triggered": False,
                    "mae_micro": 0, "mfe_micro": 0, "path_resolution": "FIXTURE",
                    "taint": 0,
                }],
            )

    def test_fixture_outcome_is_synthetic_and_sealed(self):
        ctx, arms = self.fx.evaluate()
        batch = persist_fixture_outcome_batch(
            self.fx.store,
            dataset_id=self.fx.dataset.dataset_id,
            fixture_name="p0-long-resolved",
            attachments=[{
                "subject_kind": "ARM",
                "subject_ref": arms[0].arm_id,
                "reference_plan_id": None,
                "resolver_version_id": "fixture-resolver-v1",
                "cost_model_version_id": "fixture-cost-v1",
                "status": "RESOLVED",
                "entry_time_us": M15 * 2,
                "r_low_micro": 2_000_000,
                "r_high_micro": 2_000_000,
                "exit_reason": "FIXTURE_TARGET",
                "be_triggered": False,
                "mae_micro": -250_000,
                "mfe_micro": 2_000_000,
                "path_resolution": "FIXTURE",
                "taint": 0,
            }],
        )
        row = self.fx.store.conn.execute(
            "SELECT * FROM outcome_attachments WHERE batch_id=?", (batch.batch_id,)
        ).fetchone()
        self.assertTrue(row["taint"] & int(Taint.SYNTHETIC_DATA))
        self.assertTrue(self.fx.store.conn.execute(
            "SELECT 1 FROM sys_seals WHERE aggregate_kind='outcome_batches' AND aggregate_id=?",
            (batch.batch_id,),
        ).fetchone())

    def test_fixture_outcome_inherits_subject_taint(self):
        pin = LabelSetPin.create(
            view_kind="RESEARCH",
            group_ids=(),
            selector_policy_version="per-labeler-latest-v1",
            taint=int(Taint.RETRO_LABEL),
        )
        self.fx.store.conn.execute(
            "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
            (pin.pin_id, pin.view_kind, canonical_json_text([]), pin.selector_policy_version, pin.taint),
        )
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        arms = evaluate_c0(self.fx.store, ctx_id=ctx.ctx_id)
        self.assertTrue(arms[0].taint & int(Taint.RETRO_LABEL))
        batch = persist_fixture_outcome_batch(
            self.fx.store, dataset_id=self.fx.dataset.dataset_id,
            fixture_name="taint-inheritance",
            attachments=[{
                "subject_kind": "ARM", "subject_ref": arms[0].arm_id,
                "reference_plan_id": None, "resolver_version_id": "fixture-resolver-v1",
                "cost_model_version_id": "fixture-cost-v1", "status": "RESOLVED",
                "entry_time_us": M15 * 2, "r_low_micro": 0, "r_high_micro": 0,
                "exit_reason": "FIXTURE", "be_triggered": False,
                "mae_micro": 0, "mfe_micro": 0, "path_resolution": "FIXTURE",
                "taint": 0,
            }],
        )
        taint = self.fx.store.conn.execute(
            "SELECT taint FROM outcome_attachments WHERE batch_id=?", (batch.batch_id,)
        ).fetchone()[0]
        self.assertTrue(taint & int(Taint.RETRO_LABEL))
        self.assertTrue(taint & int(Taint.SYNTHETIC_DATA))

    def test_fixture_outcome_retry_rejects_changed_content(self):
        _, arms = self.fx.evaluate()
        base = {
            "subject_kind": "ARM", "subject_ref": arms[0].arm_id,
            "reference_plan_id": None, "resolver_version_id": "fixture-resolver-v1",
            "cost_model_version_id": "fixture-cost-v1", "status": "RESOLVED",
            "entry_time_us": M15 * 2, "r_low_micro": 2_000_000,
            "r_high_micro": 2_000_000, "exit_reason": "FIXTURE_TARGET",
            "be_triggered": False, "mae_micro": -250_000, "mfe_micro": 2_000_000,
            "path_resolution": "FIXTURE", "taint": 0,
        }
        persist_fixture_outcome_batch(
            self.fx.store, dataset_id=self.fx.dataset.dataset_id,
            fixture_name="retry-fixture", attachments=[base],
        )
        changed = dict(base)
        changed["r_low_micro"] = 1_500_000
        changed["r_high_micro"] = 1_500_000
        with self.assertRaises(StoreConflict) as ctx:
            persist_fixture_outcome_batch(
                self.fx.store, dataset_id=self.fx.dataset.dataset_id,
                fixture_name="retry-fixture", attachments=[changed],
            )
        self.assertEqual(ctx.exception.kind, ConflictKind.IDENTITY_CONFLICT)

    def test_sealed_outcome_retry_rejects_semantically_same_different_subject_id(self):
        _, first_arms = self.fx.evaluate()
        common = {
            "reference_plan_id": None, "resolver_version_id": "fixture-resolver-v1",
            "cost_model_version_id": "fixture-cost-v1", "status": "RESOLVED",
            "entry_time_us": M15 * 2, "r_low_micro": 1_000_000,
            "r_high_micro": 1_000_000, "exit_reason": "FIXTURE",
            "be_triggered": False, "mae_micro": 0, "mfe_micro": 1_000_000,
            "path_resolution": "FIXTURE", "taint": 0,
        }
        persist_fixture_outcome_batch(
            self.fx.store, dataset_id=self.fx.dataset.dataset_id,
            fixture_name="subject-id-retry",
            attachments=[{"subject_kind": "ARM", "subject_ref": first_arms[0].arm_id, **common}],
        )

        pin = LabelSetPin.create(
            view_kind="OPERATIONAL", group_ids=(),
            selector_policy_version="alternate-owner-policy-v1", taint=0,
        )
        self.fx.store.conn.execute(
            "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
            (pin.pin_id, pin.view_kind, canonical_json_text([]), pin.selector_policy_version, pin.taint),
        )
        second_ctx = create_context(
            self.fx.store, capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id, macro_view_class="PIT", mode="REPLAY",
        )
        second_arms = evaluate_c0(self.fx.store, ctx_id=second_ctx.ctx_id)
        self.assertNotEqual(first_arms[0].arm_id, second_arms[0].arm_id)
        with self.assertRaises(StoreConflict) as ctx:
            persist_fixture_outcome_batch(
                self.fx.store, dataset_id=self.fx.dataset.dataset_id,
                fixture_name="subject-id-retry",
                attachments=[{"subject_kind": "ARM", "subject_ref": second_arms[0].arm_id, **common}],
            )
        self.assertEqual(ctx.exception.kind, ConflictKind.IDENTITY_CONFLICT)

    def test_outcome_member_cannot_cross_batches(self):
        _, arms = self.fx.evaluate()
        first = persist_fixture_outcome_batch(
            self.fx.store, dataset_id=self.fx.dataset.dataset_id,
            fixture_name="batch-one",
            attachments=[{
                "subject_kind": "ARM", "subject_ref": arms[0].arm_id,
                "reference_plan_id": None, "resolver_version_id": "fixture-resolver-v1",
                "cost_model_version_id": "fixture-cost-v1", "status": "RESOLVED",
                "entry_time_us": M15 * 2, "r_low_micro": 1_000_000,
                "r_high_micro": 1_000_000, "exit_reason": "FIXTURE",
                "be_triggered": False, "mae_micro": 0, "mfe_micro": 1_000_000,
                "path_resolution": "FIXTURE", "taint": 0,
            }],
        )
        outcome_id = self.fx.store.conn.execute(
            "SELECT outcome_id FROM outcome_attachments WHERE batch_id=?", (first.batch_id,)
        ).fetchone()[0]
        second = OutcomeBatch.create(
            dataset_id=self.fx.dataset.dataset_id, fixture_name="batch-two"
        )
        self.fx.store.conn.execute(
            "INSERT INTO outcome_batches VALUES (?,?,?)",
            (second.batch_id, second.dataset_id, second.fixture_name),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "OUTCOME_MEMBER_BATCH_MISMATCH"):
            self.fx.store.conn.execute(
                "INSERT INTO outcome_batch_members VALUES (?,?,?)",
                (second.batch_id, outcome_id, "0" * 64),
            )

    def test_unknown_arm_outcome_subject_fails_cleanly(self):
        with self.assertRaisesRegex(ValueError, "unknown .* outcome subject"):
            persist_fixture_outcome_batch(
                self.fx.store, dataset_id=self.fx.dataset.dataset_id,
                fixture_name="missing-arm",
                attachments=[{
                    "subject_kind": "ARM", "subject_ref": "arm_" + "f" * 64,
                    "reference_plan_id": None, "resolver_version_id": "fixture-resolver-v1",
                    "cost_model_version_id": "fixture-cost-v1", "status": "RESOLVED",
                    "entry_time_us": M15 * 2, "r_low_micro": 0, "r_high_micro": 0,
                    "exit_reason": "FIXTURE", "be_triggered": False,
                    "mae_micro": 0, "mfe_micro": 0, "path_resolution": "FIXTURE",
                    "taint": 0,
                }],
            )

    def test_shadow_report_is_deterministic_read_only_and_no_order(self):
        ctx, _ = self.fx.evaluate()
        tables = (
            "evaluation_contexts", "gate_results", "arm_results",
            "evaluation_unit_members", "sys_seals", "run_aggregate_refs",
        )
        before = {
            table: self.fx.store.conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in tables
        }

        report = build_shadow_report(
            self.fx.store.path, self.fx.manifest.manifest_id
        )
        rendered = render_shadow_report_json(
            self.fx.store.path, self.fx.manifest.manifest_id
        )
        after = {
            table: self.fx.store.conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in tables
        }

        self.assertEqual(before, after)
        self.assertEqual(
            rendered,
            render_shadow_report_json(
                self.fx.store.path, self.fx.manifest.manifest_id
            ),
        )
        other = Fixture(
            Path(self.tmp.name) / "shadow-second",
            attempt_id="shadow-second-attempt",
        )
        self.addCleanup(other.store.close)
        other.evaluate()
        self.assertEqual(
            rendered,
            render_shadow_report_json(
                other.store.path, other.manifest.manifest_id
            ),
        )
        self.assertEqual(report["authority"], "NO_ORDER")
        self.assertEqual(report["owner_strategy_status"], "NOT_PRESENT")
        self.assertEqual(
            report["entry_semantics_status"],
            "OWNER_POLICY_FROZEN_RESEARCH_DETAILS_PENDING",
        )
        self.assertEqual(
            report["replay_digest"],
            replay_digest_for_store(self.fx.store, self.fx.manifest.manifest_id),
        )
        self.assertEqual(report["context_count"], 1)
        summary = report["contexts"][0]
        self.assertEqual(summary["ctx_id"], ctx.ctx_id)
        self.assertEqual((summary["candidate_count"], summary["arm_count"]), (1, 1))
        strategy = summary["strategies"][0]
        self.assertEqual(
            (strategy["strategy_key"], strategy["strategy_version"]),
            ("C0_MINIMAL_CONTROL", "v1"),
        )
        self.assertEqual(strategy["decisions"]["ACCEPT"], 1)

    def test_shadow_report_rejects_unknown_manifest(self):
        with self.assertRaisesRegex(ValueError, "unknown run manifest"):
            build_shadow_report(self.fx.store.path, "manifest-missing")

    def test_shadow_report_fails_on_unconfirmed_capture_dependency(self):
        ctx, _ = self.fx.evaluate()
        partial = RunManifest(
            "manifest-shadow-partial", "2" * 64, None, "REPLAY", "{}"
        )
        self.fx.store.put(partial)
        with self.fx.store.transaction():
            self.fx.store.conn.execute(
                "INSERT INTO run_aggregate_refs VALUES (?,?,?)",
                (partial.manifest_id, "evaluation_contexts", ctx.ctx_id),
            )
        with self.assertRaisesRegex(
            ValueError, "lacks confirmed capture unit"
        ):
            build_shadow_report(self.fx.store.path, partial.manifest_id)

    def test_p1_track_a_integrates_without_inventing_pending_gates(self):
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        result = evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)

        self.assertEqual(len(result.c0_arms), 1)
        self.assertEqual(len(result.owner_arms), 2)
        self.assertEqual(result.c0_arms[0].decision, "ACCEPT")
        self.assertEqual(
            {arm.decision for arm in result.owner_arms},
            {"ABSTAIN"},
        )
        self.assertTrue(
            self.fx.store.conn.execute(
                """SELECT 1 FROM sys_seals
                   WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=?""",
                (ctx.ctx_id,),
            ).fetchone()
        )
        self.assertEqual(
            result,
            evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id),
        )

        gates = {
            row["gate_kind"]: row
            for row in self.fx.store.conn.execute(
                """SELECT * FROM gate_results
                   WHERE ctx_id=? AND candidate_id=?""",
                (ctx.ctx_id, self.fx.candidate.candidate_id),
            )
        }
        self.assertEqual(gates["DATA_QUALITY"]["outcome"], "PASS")
        self.assertEqual(gates["M15_COORDINATION"]["outcome"], "NOT_EVALUABLE")
        self.assertEqual(gates["H4_CONTEXT"]["outcome"], "NOT_EVALUABLE")
        self.assertEqual(gates["H1_CONTEXT"]["outcome"], "NOT_EVALUABLE")
        self.assertEqual(gates["CORRECTION_LOCATION"]["outcome"], "NOT_APPLICABLE")
        self.assertEqual(gates["CORRECTION_LOCATION"]["reason_code"], "NO_LABEL_PIN")
        self.assertEqual(
            json.loads(gates["CORRECTION_LOCATION"]["measurements_json"]), []
        )
        self.assertEqual(gates["SESSION_DAY"]["outcome"], "NOT_EVALUABLE")
        self.assertEqual(gates["NEWS_RISK"]["outcome"], "NOT_EVALUABLE")
        self.assertEqual(gates["SPREAD_COST"]["outcome"], "NOT_EVALUABLE")

        for arm in result.owner_arms:
            reasons = set(json.loads(arm.reason_codes_json))
            self.assertIn("M15_COORDINATION_NOT_EVALUABLE", reasons)
            self.assertIn("H4_CONTEXT_NOT_EVALUABLE", reasons)
            self.assertNotIn("H1_CONTEXT_NOT_EVALUABLE", reasons)
            self.assertNotIn("CORRECTION_LOCATION_NOT_APPLICABLE", reasons)
            plan = json.loads(arm.plan_json)
            self.assertEqual(plan["execution"], "NONE")
            self.assertTrue(plan["research_only"])

    def test_p1_correction_location_measures_pinned_h4_depth_without_gating(self):
        pin, group = self._seed_h4_correction_pin(depth_ppm=382_000)
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        result = evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)

        gate = self.fx.store.conn.execute(
            """SELECT * FROM gate_results
               WHERE ctx_id=? AND candidate_id=?
                 AND gate_kind='CORRECTION_LOCATION'""",
            (ctx.ctx_id, self.fx.candidate.candidate_id),
        ).fetchone()
        self.assertIsNotNone(gate)
        self.assertEqual(gate["outcome"], "NOT_APPLICABLE")
        self.assertEqual(gate["reason_code"], "H4_CORRECTION_DEPTH_MEASURED")
        self.assertEqual(
            json.loads(gate["measurements_json"]),
            [{"name": "correction_depth_ppm", "unit": "ppm", "value": 382_000}],
        )
        refs = json.loads(gate["input_refs_json"])
        self.assertIn(
            {"kind": "LABEL_GROUP", "ref": group.group_id},
            refs,
        )
        for arm in result.owner_arms:
            self.assertEqual(arm.decision, "ABSTAIN")
            self.assertNotIn(
                "CORRECTION_LOCATION_NOT_APPLICABLE",
                json.loads(arm.reason_codes_json),
            )

    def test_p1_correction_location_excludes_late_operational_label(self):
        pin, _ = self._seed_h4_correction_pin(submitted_offset_us=1)
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)
        gate = self.fx.store.conn.execute(
            """SELECT * FROM gate_results
               WHERE ctx_id=? AND candidate_id=?
                 AND gate_kind='CORRECTION_LOCATION'""",
            (ctx.ctx_id, self.fx.candidate.candidate_id),
        ).fetchone()
        self.assertEqual(gate["reason_code"], "PINNED_H4_GROUP_NOT_CAUSAL")
        self.assertEqual(json.loads(gate["measurements_json"]), [])

    def test_p1_correction_location_research_pin_rejects_late_label(self):
        pin, _ = self._seed_h4_correction_pin(
            submitted_offset_us=1,
            pin_view_kind="RESEARCH",
        )
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)
        gate = self.fx.store.conn.execute(
            """SELECT * FROM gate_results
               WHERE ctx_id=? AND candidate_id=?
                 AND gate_kind='CORRECTION_LOCATION'""",
            (ctx.ctx_id, self.fx.candidate.candidate_id),
        ).fetchone()
        self.assertEqual(gate["reason_code"], "PINNED_H4_GROUP_NOT_CAUSAL")
        self.assertEqual(json.loads(gate["measurements_json"]), [])

    def test_p1_correction_location_does_not_filter_pin_into_false_singleton(self):
        _, causal_group = self._seed_h4_correction_pin(
            study_id="p1-correction-causal",
            labeler_id="ali-a",
            request_key="p1-correction-causal-v1",
            pin_view_kind="RESEARCH",
        )
        _, late_group = self._seed_h4_correction_pin(
            study_id="p1-correction-late",
            labeler_id="ali-b",
            request_key="p1-correction-late-v1",
            submitted_offset_us=1,
            pin_view_kind="RESEARCH",
        )
        pin = LabelSetPin.create(
            view_kind="RESEARCH",
            group_ids=(causal_group.group_id, late_group.group_id),
            selector_policy_version="per-labeler-latest-v1",
            taint=0,
        )
        with self.fx.store.transaction():
            self.fx.store.conn.execute(
                "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
                (
                    pin.pin_id,
                    pin.view_kind,
                    canonical_json_text(list(pin.group_ids)),
                    pin.selector_policy_version,
                    pin.taint,
                ),
            )
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)
        gate = self.fx.store.conn.execute(
            """SELECT * FROM gate_results
               WHERE ctx_id=? AND candidate_id=?
                 AND gate_kind='CORRECTION_LOCATION'""",
            (ctx.ctx_id, self.fx.candidate.candidate_id),
        ).fetchone()
        self.assertEqual(gate["reason_code"], "PINNED_H4_GROUP_NOT_CAUSAL")
        refs = json.loads(gate["input_refs_json"])
        label_refs = {item["ref"] for item in refs if item["kind"] == "LABEL_GROUP"}
        self.assertEqual(
            label_refs,
            {causal_group.group_id, late_group.group_id},
        )
        self.assertEqual(json.loads(gate["measurements_json"]), [])

    def test_p1_correction_location_marks_unsealed_pinned_h4_group_unmeasured(self):
        pin, _ = self._seed_h4_correction_pin(seal_group=False)
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=pin.pin_id,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        result = evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)
        gate = self.fx.store.conn.execute(
            """SELECT * FROM gate_results
               WHERE ctx_id=? AND candidate_id=?
                 AND gate_kind='CORRECTION_LOCATION'""",
            (ctx.ctx_id, self.fx.candidate.candidate_id),
        ).fetchone()
        self.assertEqual(gate["reason_code"], "H4_LABEL_GROUP_UNSEALED")
        self.assertEqual(json.loads(gate["measurements_json"]), [])
        self.assertTrue(
            self.fx.store.conn.execute(
                """SELECT 1 FROM sys_seals
                   WHERE aggregate_kind='evaluation_contexts'
                     AND aggregate_id=?""",
                (ctx.ctx_id,),
            ).fetchone()
        )
        self.assertTrue(all(arm.decision == "ABSTAIN" for arm in result.owner_arms))

    def test_p1_track_a_replay_is_deterministic_across_fresh_attempts(self):
        ctx = create_context(
            self.fx.store,
            capture_unit_id=self.fx.capture_unit.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)
        confirm_aggregate(
            self.fx.store,
            self.fx.manifest.manifest_id,
            "capture_units",
            self.fx.capture_unit.capture_unit_id,
        )
        confirm_aggregate(
            self.fx.store,
            self.fx.manifest.manifest_id,
            "evaluation_contexts",
            ctx.ctx_id,
        )

        other = Fixture(
            Path(self.tmp.name) / "p1-track-a-second",
            attempt_id="p1-track-a-second-attempt",
        )
        self.addCleanup(other.store.close)
        other_ctx = create_context(
            other.store,
            capture_unit_id=other.capture_unit.capture_unit_id,
            label_pin_id=None,
            macro_view_class="PIT",
            mode="REPLAY",
        )
        evaluate_p1_track_a(other.store, ctx_id=other_ctx.ctx_id)
        confirm_aggregate(
            other.store,
            other.manifest.manifest_id,
            "capture_units",
            other.capture_unit.capture_unit_id,
        )
        confirm_aggregate(
            other.store,
            other.manifest.manifest_id,
            "evaluation_contexts",
            other_ctx.ctx_id,
        )

        self.assertEqual(
            replay_digest_for_store(
                self.fx.store, self.fx.manifest.manifest_id
            ),
            replay_digest_for_store(
                other.store, other.manifest.manifest_id
            ),
        )
        self.assertEqual(
            render_shadow_report_json(
                self.fx.store.path, self.fx.manifest.manifest_id
            ),
            render_shadow_report_json(
                other.store.path, other.manifest.manifest_id
            ),
        )

        report = build_shadow_report(
            self.fx.store.path, self.fx.manifest.manifest_id
        )
        self.assertEqual(
            report["owner_strategy_status"], "TRACK_A_RESEARCH_INTEGRATED"
        )
        self.assertEqual(
            report["entry_semantics_status"],
            "OWNER_POLICY_FROZEN_RESEARCH_DETAILS_PENDING",
        )
        strategies = report["contexts"][0]["strategies"]
        self.assertEqual(len(strategies), 3)
        self.assertEqual(
            sum(
                item["arm_count"]
                for item in strategies
                if item["strategy_key"] == "OWNER_TRACK_A"
            ),
            2,
        )

    def test_p1_track_a_refuses_to_retrofit_sealed_c0_context(self):
        ctx, _ = self.fx.evaluate()
        with self.assertRaisesRegex(
            ValueError, "does not contain complete P1 Track A arms"
        ):
            evaluate_p1_track_a(self.fx.store, ctx_id=ctx.ctx_id)

    def test_cross_dataset_semantic_prefix_and_control(self):
        # T is the decision time. A revision available only after T must not alter the projection.
        root_late = Path(self.tmp.name) / "late"
        late = Fixture(root_late, attempt_id="late-attempt", extra_availability=M15 * 3)
        self.addCleanup(late.store.close)
        late_ctx, _ = late.evaluate()
        base_ctx, _ = self.fx.evaluate()
        self.assertEqual(project_context(self.fx.store, base_ctx.ctx_id), project_context(late.store, late_ctx.ctx_id))

        # Control: the same revision made available before T changes visible_fact_digest.
        root_early = Path(self.tmp.name) / "early"
        early = Fixture(root_early, attempt_id="early-attempt", extra_availability=M15 + 1)
        self.addCleanup(early.store.close)
        early_ctx, _ = early.evaluate()
        self.assertNotEqual(
            project_context(self.fx.store, base_ctx.ctx_id),
            project_context(early.store, early_ctx.ctx_id),
        )


if __name__ == "__main__":
    unittest.main()
