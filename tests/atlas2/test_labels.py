import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas2.core.enums import AvailabilityBasis
from atlas2.core.errors import HoldoutLocked
from atlas2.core.ids import make_id
from atlas2.core.taint import Taint
from atlas2.data.datasets import freeze_dataset, make_bar_fact
from atlas2.data.ingest import ingest_source_bytes
from atlas2.labels.agreement import (
    abstention_rate,
    anchor_agreement,
    cohens_kappa,
    direction_agreement,
)
from atlas2.labels.select import LabelSelectionService
from atlas2.labels.submit import LabelSubmissionService
from atlas2.labels.tasks import LabelTaskService, blind_transform
from atlas2.model.data import FactLink
from atlas2.model.labels import LabelTaskSeed
from atlas2.research.registry import ResearchRegistry
from atlas2.store.backup import verify
from atlas2.store.repository import Store, StoreConflict, ConflictKind

M15 = 15 * 60 * 1_000_000
H4 = 4 * 60 * 60 * 1_000_000
CLOCK = make_id("comp", "clock-profile-v1", {"zone": "UTC"})
COMP = make_id("comp", "normalizer-v1", {"name": "test"})
SPEC = make_id("comp", "instrument-spec-v1", {"symbol": "EURUSD", "digits": 5})


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "store")
        self.addCleanup(self.store.close)
        obs = ingest_source_bytes(
            self.store,
            b"labels-source",
            source_id="synthetic",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=0,
            clock_profile_id=CLOCK,
        )
        bar = make_bar_fact(
            instrument_id="EURUSD",
            timeframe="M15",
            price_side="BID",
            open_time_us=0,
            close_time_us=M15,
            open=100,
            high=110,
            low=90,
            close=105,
            tick_volume=1,
            real_volume=None,
            spread_points=1,
            spread_semantics="LAST",
            instrument_spec_id=SPEC,
        )
        link = FactLink(
            bar.fact_id,
            obs.obs_id,
            "row:1",
            COMP,
            M15,
            AvailabilityBasis.BAR_CLOSE_RULE,
            0,
        )
        self.store.put_many([bar, link])
        self.dataset = freeze_dataset(
            self.store,
            [("BAR", bar.fact_id, link.obs_id, link.locator)],
            coverage={"instruments": ["EURUSD"], "start_us": 0, "end_us": H4 * 4},
            causal_policy={"bar_publication_lag_us": 0},
            htf_policy={"base": "M15", "alignment": "UTC"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=CLOCK,
            instrument_specs={"EURUSD": SPEC},
            tzdata_version="synthetic-v1",
            display_name="labels-fixture",
            built_at_us=H4 * 5,
        )
        self.tasks = LabelTaskService(self.store)
        self.submit = LabelSubmissionService(self.store)
        self.select = LabelSelectionService(self.store)

    def make_task(
        self,
        *,
        study="study-1",
        repeat=0,
        blind="NONE",
        actor="ali",
        grant_ids=(),
        secret=None,
    ):
        return self.tasks.create(
            study_id=study,
            instrument_id="EURUSD",
            timeframe="H4",
            dataset_id=self.dataset.dataset_id,
            visible_data_cutoff_us=H4 * 2,
            lookback_bars=2,
            blind_mode=blind,
            repeat_index=repeat,
            actor=actor,
            purpose="label-study",
            grant_ids=grant_ids,
            request_key_prefix=f"task:{study}:{repeat}",
            study_secret=secret,
        )

    def interpretation(self, *, trend="BULLISH", rank=1, probability=700_000):
        return {
            "rank": rank,
            "probability_ppm": probability,
            "trend": trend,
            "confidence": 4,
            "correction_depth_ppm": 382_000,
            "correction_class": "MINOR",
            "reason": "synthetic",
            "anchors": [
                {
                    "role": "IMPULSE_START",
                    "bar_open_time_us": 0,
                    "side": "LOW",
                    "price": 100,
                    "confirmation_time_us": H4,
                    "time_status": "EXACT_BAR",
                },
                {
                    "role": "IMPULSE_END",
                    "bar_open_time_us": H4,
                    "side": "HIGH",
                    "price": 120,
                    "confirmation_time_us": H4 * 2,
                    "time_status": "EXACT_BAR",
                },
            ],
        }

    def test_task_seed_before_transform_and_hmac_is_deterministic(self):
        seed, task = self.make_task(blind="IDENTITY_PRICE", secret=b"study-secret")
        second_seed, second_task = self.make_task(
            blind="IDENTITY_PRICE", secret=b"study-secret"
        )
        self.assertEqual(seed, second_seed)
        self.assertEqual(task, second_task)
        transform = json.loads(task.transform_json)
        self.assertTrue(transform["hide_identity"])
        self.assertEqual(len(transform["price_transform_seed_hmac_sha256"]), 64)
        self.assertNotIn("study-secret", task.transform_json)
        other = blind_transform(seed, b"different-secret")
        self.assertNotEqual(
            transform["price_transform_seed_hmac_sha256"],
            other["price_transform_seed_hmac_sha256"],
        )

    def test_holdout_request_identity_tracks_full_task_seed(self):
        registry = ResearchRegistry(self.store)
        experiment = registry.register_experiment(
            {"hypothesis": "labels-seed"}, "ali", "label-seed-exp", "CONFIRMATORY"
        )
        segment = registry.add_holdout_segment("EURUSD", 0, H4 * 2)
        grant = registry.grant_holdout(
            experiment.experiment_id, segment.segment_id, "ali", "label-seed-grant"
        )
        first_seed, _ = self.tasks.create(
            study_id="same-study",
            instrument_id="EURUSD",
            timeframe="H4",
            dataset_id=self.dataset.dataset_id,
            visible_data_cutoff_us=H4 * 2,
            lookback_bars=2,
            blind_mode="NONE",
            repeat_index=0,
            actor="ali",
            purpose="label-study",
            grant_ids=(grant.grant_id,),
            request_key_prefix="same-prefix",
        )
        second_seed, _ = self.tasks.create(
            study_id="same-study",
            instrument_id="EURUSD",
            timeframe="H4",
            dataset_id=self.dataset.dataset_id,
            visible_data_cutoff_us=H4 * 2,
            lookback_bars=1,
            blind_mode="NONE",
            repeat_index=0,
            actor="ali",
            purpose="label-study",
            grant_ids=(grant.grant_id,),
            request_key_prefix="same-prefix",
        )
        self.assertNotEqual(first_seed.seed_id, second_seed.seed_id)
        self.assertEqual(
            self.store.conn.execute(
                "SELECT count(*) FROM research_exposures WHERE route='LABEL_TASK'"
            ).fetchone()[0],
            2,
        )

    def test_identity_price_requires_secret(self):
        seed = LabelTaskSeed.create(
            "study",
            "EURUSD",
            "H4",
            self.dataset.dataset_id,
            H4 * 2,
            2,
            "IDENTITY_PRICE",
            0,
        )
        with self.assertRaises(ValueError):
            blind_transform(seed, None)

    def test_historical_task_creation_uses_label_task_holdout_route(self):
        registry = ResearchRegistry(self.store)
        experiment = registry.register_experiment(
            {"hypothesis": "labels"}, "ali", "label-exp", "CONFIRMATORY"
        )
        segment = registry.add_holdout_segment("EURUSD", 0, H4 * 2)
        grant = registry.grant_holdout(
            experiment.experiment_id, segment.segment_id, "ali", "label-grant"
        )
        with self.assertRaises(HoldoutLocked):
            self.make_task(study="protected")
        self.make_task(study="protected", grant_ids=(grant.grant_id,))
        route = self.store.conn.execute(
            "SELECT route FROM research_exposures ORDER BY served_at_us DESC LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(route, "LABEL_TASK")

    def test_operational_submission_retry_and_changed_payload_conflict(self):
        _, task = self.make_task()
        first = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="submit-1",
            kind="INTERPRETATIONS",
            label_mode="OPERATIONAL",
            interpretations=[self.interpretation()],
        )
        retry = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="submit-1",
            kind="INTERPRETATIONS",
            label_mode="OPERATIONAL",
            interpretations=[self.interpretation()],
        )
        self.assertEqual(first, retry)
        self.assertEqual(first.operational_available_at_us, first.submitted_at_us)
        self.assertEqual(
            self.store.conn.execute(
                "SELECT count(*) FROM label_groups WHERE group_id=?", (first.group_id,)
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(StoreConflict) as ctx:
            self.submit.submit(
                task_id=task.task_id,
                labeler_id="ali",
                request_key="submit-1",
                kind="INTERPRETATIONS",
                label_mode="OPERATIONAL",
                interpretations=[self.interpretation(trend="BEARISH")],
            )
        self.assertEqual(ctx.exception.kind, ConflictKind.LOGICAL_KEY_CONFLICT)

    def test_submission_request_key_is_scoped_by_task(self):
        _, first_task = self.make_task(study="request-scope-a")
        _, second_task = self.make_task(study="request-scope-b")
        first = self.submit.submit(
            task_id=first_task.task_id,
            labeler_id="ali",
            request_key="same-client-key",
            kind="ABSTENTION",
            label_mode="OPERATIONAL",
            abstention_reason="first",
        )
        second = self.submit.submit(
            task_id=second_task.task_id,
            labeler_id="ali",
            request_key="same-client-key",
            kind="ABSTENTION",
            label_mode="OPERATIONAL",
            abstention_reason="second",
        )
        self.assertNotEqual(first.group_id, second.group_id)
        self.assertEqual(first.request_key, second.request_key)

    def test_revision_abstention_is_not_skipped_by_operational_selector(self):
        _, task = self.make_task()
        first = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="first",
            kind="INTERPRETATIONS",
            label_mode="OPERATIONAL",
            interpretations=[self.interpretation()],
        )
        second = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="second",
            kind="ABSTENTION",
            label_mode="OPERATIONAL",
            abstention_reason="unclear",
            supersedes_group_id=first.group_id,
            revision_reason="new evidence",
        )
        early = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=first.submitted_at_us,
            authorized_labelers=("ali",),
            selector_policy_version="latest-authorized-owner-v1",
        )
        late = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=second.submitted_at_us,
            authorized_labelers=("ali",),
            selector_policy_version="latest-authorized-owner-v1",
        )
        self.assertEqual(early.group_ids, (first.group_id,))
        self.assertEqual(late.group_ids, (second.group_id,))
        self.assertEqual(
            self.select.groups_for_pin(late.pin_id)[0]["kind"], "ABSTENTION"
        )
        with self.assertRaises(ValueError):
            self.submit.submit(
                task_id=task.task_id,
                labeler_id="ali",
                request_key="fork",
                kind="ABSTENTION",
                label_mode="OPERATIONAL",
                abstention_reason="fork",
                supersedes_group_id=first.group_id,
                revision_reason="bad fork",
            )

    def test_retrospective_never_enters_operational_view(self):
        _, task = self.make_task(study="retro")
        retro = self.submit.submit(
            task_id=task.task_id,
            labeler_id="researcher",
            request_key="retro-1",
            kind="INTERPRETATIONS",
            label_mode="RETROSPECTIVE",
            interpretations=[self.interpretation()],
        )
        self.assertIsNone(retro.operational_available_at_us)
        self.assertTrue(retro.taint & int(Taint.RETRO_LABEL))
        operational = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=retro.submitted_at_us,
            authorized_labelers=("researcher",),
            selector_policy_version="per-labeler-latest-v1",
        )
        research = self.select.select(
            task_id=task.task_id,
            view_kind="RESEARCH",
            as_of_us=retro.submitted_at_us,
            authorized_labelers=("researcher",),
            selector_policy_version="per-labeler-latest-v1",
        )
        self.assertEqual(operational.group_ids, ())
        self.assertEqual(research.group_ids, (retro.group_id,))
        self.assertTrue(research.taint & int(Taint.RETRO_LABEL))

    def test_inferred_anchor_taints_group_and_legacy_unknown_time_is_allowed(self):
        _, task = self.make_task(study="legacy")
        spec = self.interpretation()
        spec["anchors"][0]["time_status"] = "INFERRED_RECONSTRUCTION"
        group = self.submit.submit(
            task_id=task.task_id,
            labeler_id="engine",
            request_key="engine-1",
            kind="INTERPRETATIONS",
            label_mode="ENGINE",
            interpretations=[spec],
        )
        self.assertTrue(group.taint & int(Taint.INFERRED_RECONSTRUCTION))

        _, task2 = self.make_task(study="legacy2")
        legacy_spec = self.interpretation()
        legacy_spec["anchors"] = [
            {
                "role": "IMPULSE_START",
                "bar_open_time_us": None,
                "side": "LOW",
                "price": 99,
                "confirmation_time_us": None,
                "time_status": "UNKNOWN_LEGACY",
            }
        ]
        legacy = self.submit.submit(
            task_id=task2.task_id,
            labeler_id="legacy:owner",
            request_key="legacy-1",
            kind="INTERPRETATIONS",
            label_mode="LEGACY_IMPORT",
            interpretations=[legacy_spec],
        )
        self.assertTrue(legacy.taint & int(Taint.INFERRED_RECONSTRUCTION))

    def test_anchor_must_be_complete_and_confirmation_is_causal(self):
        _, task = self.make_task(study="bad-anchor")
        bad = self.interpretation()
        bad["anchors"][1]["bar_open_time_us"] = H4 * 2
        bad["anchors"][1]["confirmation_time_us"] = H4 * 3
        with self.assertRaisesRegex(ValueError, "complete"):
            self.submit.submit(
                task_id=task.task_id,
                labeler_id="ali",
                request_key="bad-anchor",
                kind="INTERPRETATIONS",
                label_mode="RETROSPECTIVE",
                interpretations=[bad],
            )

        _, task2 = self.make_task(study="bad-confirm")
        bad2 = self.interpretation()
        bad2["anchors"][1]["confirmation_time_us"] = H4 + 1
        with self.assertRaisesRegex(ValueError, "precede"):
            self.submit.submit(
                task_id=task2.task_id,
                labeler_id="ali",
                request_key="bad-confirm",
                kind="INTERPRETATIONS",
                label_mode="RETROSPECTIVE",
                interpretations=[bad2],
            )

    def test_rank_probability_and_sealed_children(self):
        _, task = self.make_task(study="prob")
        with self.assertRaisesRegex(ValueError, "probability"):
            self.submit.submit(
                task_id=task.task_id,
                labeler_id="ali",
                request_key="prob-bad",
                kind="INTERPRETATIONS",
                label_mode="RETROSPECTIVE",
                interpretations=[
                    self.interpretation(rank=1, probability=600_000),
                    self.interpretation(rank=2, probability=500_000),
                ],
            )
        group = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="prob-good",
            kind="INTERPRETATIONS",
            label_mode="RETROSPECTIVE",
            interpretations=[self.interpretation(rank=1, probability=1_000_000)],
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "SEAL_VIOLATION"):
            self.store.conn.execute(
                """INSERT INTO label_interpretations
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "lint_" + "0" * 64,
                    group.group_id,
                    2,
                    None,
                    "BEARISH",
                    3,
                    None,
                    None,
                    None,
                ),
            )

    def test_label_set_pin_changes_after_revision_and_is_immutable(self):
        _, task = self.make_task(study="pin")
        first = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="p1",
            kind="INTERPRETATIONS",
            label_mode="OPERATIONAL",
            interpretations=[self.interpretation()],
        )
        pin1 = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=first.submitted_at_us,
            authorized_labelers=("ali",),
            selector_policy_version="latest-authorized-owner-v1",
        )
        second = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="p2",
            kind="ABSTENTION",
            label_mode="OPERATIONAL",
            abstention_reason="later",
            supersedes_group_id=first.group_id,
            revision_reason="revision",
        )
        pin2 = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=second.submitted_at_us,
            authorized_labelers=("ali",),
            selector_policy_version="latest-authorized-owner-v1",
        )
        self.assertNotEqual(pin1.pin_id, pin2.pin_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                "UPDATE label_set_pins SET taint=taint WHERE pin_id=?", (pin1.pin_id,)
            )

    def test_multi_labeler_selection_policy_is_versioned_and_deterministic(self):
        _, task = self.make_task(study="multi-owner")
        first = self.submit.submit(
            task_id=task.task_id,
            labeler_id="owner-a",
            request_key="a1",
            kind="INTERPRETATIONS",
            label_mode="OPERATIONAL",
            interpretations=[self.interpretation(trend="BULLISH")],
        )
        second = self.submit.submit(
            task_id=task.task_id,
            labeler_id="owner-b",
            request_key="b1",
            kind="ABSTENTION",
            label_mode="OPERATIONAL",
            abstention_reason="unclear",
        )
        per_labeler = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=second.submitted_at_us,
            authorized_labelers=("owner-a", "owner-b"),
            selector_policy_version="per-labeler-latest-v1",
        )
        self.assertEqual(per_labeler.group_ids, tuple(sorted((first.group_id, second.group_id))))
        owner_latest = self.select.select(
            task_id=task.task_id,
            view_kind="OPERATIONAL",
            as_of_us=second.submitted_at_us,
            authorized_labelers=("owner-a", "owner-b"),
            selector_policy_version="latest-authorized-owner-v1",
        )
        self.assertEqual(owner_latest.group_ids, (second.group_id,))
        self.assertEqual(self.select.groups_for_pin(owner_latest.pin_id)[0]["kind"], "ABSTENTION")

    def test_raw_group_cutoff_and_inferred_taint_are_enforced(self):
        _, task = self.make_task(study="raw-causal")
        submitted = 2_000_000_000_000_000
        with self.assertRaisesRegex(sqlite3.IntegrityError, "LABEL_TASK_CUTOFF_MISMATCH"):
            self.store.conn.execute(
                """INSERT INTO label_groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "lgrp_" + "2" * 64,
                    task.task_id,
                    "raw",
                    "raw-cutoff",
                    "ABSTENTION",
                    "RETROSPECTIVE",
                    submitted,
                    H4,
                    None,
                    None,
                    None,
                    "unclear",
                    "DECLARED",
                    0,
                    int(Taint.RETRO_LABEL),
                ),
            )

        group = self.submit.submit(
            task_id=task.task_id,
            labeler_id="raw-engine",
            request_key="inferred-parent",
            kind="INTERPRETATIONS",
            label_mode="ENGINE",
            interpretations=[self.interpretation()],
        )
        interpretation_id = self.store.conn.execute(
            "SELECT interpretation_id FROM label_interpretations WHERE group_id=?",
            (group.group_id,),
        ).fetchone()[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "INFERRED_ANCHOR_REQUIRES_TAINT"):
            self.store.conn.execute(
                "INSERT INTO label_anchors VALUES (?,?,?,?,?,?,?,?)",
                (
                    "lanch_" + "2" * 64,
                    interpretation_id,
                    "CORRECTION_EXTREME",
                    0,
                    "LOW",
                    95,
                    H4,
                    "INFERRED_RECONSTRUCTION",
                ),
            )

        # Direct raw evidence cannot insert inferred anchors under an untainted group either.
        raw_group = "lgrp_" + "3" * 64
        self.store.conn.execute(
            """INSERT INTO label_groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                raw_group,
                task.task_id,
                "raw-inferred",
                "raw-inferred",
                "INTERPRETATIONS",
                "ENGINE",
                submitted + 1,
                H4 * 2,
                None,
                None,
                None,
                None,
                "DECLARED",
                0,
                0,
            ),
        )
        raw_interpretation = "lint_" + "3" * 64
        self.store.conn.execute(
            "INSERT INTO label_interpretations VALUES (?,?,?,?,?,?,?,?,?)",
            (raw_interpretation, raw_group, 1, None, "BULLISH", 3, None, None, None),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "INFERRED_ANCHOR_REQUIRES_TAINT"):
            self.store.conn.execute(
                "INSERT INTO label_anchors VALUES (?,?,?,?,?,?,?,?)",
                (
                    "lanch_" + "3" * 64,
                    raw_interpretation,
                    "IMPULSE_START",
                    0,
                    "LOW",
                    95,
                    H4,
                    "INFERRED_RECONSTRUCTION",
                ),
            )

    def test_agreement_metrics_are_deterministic(self):
        pairs = [
            ("BULLISH", "BULLISH"),
            ("BEARISH", "BULLISH"),
            (None, "BEARISH"),
        ]
        self.assertEqual(direction_agreement(pairs)["agreement_ppm"], 500_000)
        self.assertEqual(abstention_rate(pairs)["abstention_count"], 1)
        self.assertEqual(cohens_kappa(pairs)["kappa_ppm"], 0)
        with self.assertRaises(ValueError):
            direction_agreement([("INVALID", "BULLISH")])
        anchors = anchor_agreement(
            [(0, 0), (H4, H4 * 2), (None, H4)],
            timeframe_us=H4,
        )
        self.assertEqual(anchors["usable_count"], 2)
        self.assertEqual(anchors["within_0_bars_count"], 1)
        self.assertEqual(anchors["within_1_bars_count"], 2)

    def test_raw_replace_cannot_overwrite_logical_task_identity(self):
        seed, task = self.make_task(study="raw-replace")
        raw = sqlite3.connect(self.store.path, isolation_level=None)
        try:
            raw.execute("PRAGMA recursive_triggers=OFF")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "IMMUTABLE_EVIDENCE"):
                raw.execute(
                    """INSERT OR REPLACE INTO label_task_seeds
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "lseed_" + "0" * 64,
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
            with self.assertRaisesRegex(sqlite3.IntegrityError, "IMMUTABLE_EVIDENCE"):
                raw.execute(
                    "INSERT OR REPLACE INTO label_tasks VALUES (?,?,?)",
                    ("ltask_" + "0" * 64, task.seed_id, task.transform_json),
                )
        finally:
            raw.close()

    def test_raw_anchor_time_guard_and_invalid_group_seal(self):
        _, task = self.make_task(study="raw-semantics")
        submitted = 2_000_000_000_000_000
        group_id = "lgrp_" + "1" * 64
        self.store.conn.execute(
            """INSERT INTO label_groups VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                group_id,
                task.task_id,
                "raw-labeler",
                "raw-key",
                "INTERPRETATIONS",
                "RETROSPECTIVE",
                submitted,
                H4 * 2,
                None,
                None,
                None,
                None,
                "DECLARED",
                0,
                int(Taint.RETRO_LABEL),
            ),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "INVALID_LABEL_GROUP_SEAL"):
            self.store.seal("label_groups", group_id)

        interpretation_id = "lint_" + "1" * 64
        self.store.conn.execute(
            "INSERT INTO label_interpretations VALUES (?,?,?,?,?,?,?,?,?)",
            (
                interpretation_id,
                group_id,
                1,
                None,
                "BULLISH",
                3,
                None,
                None,
                None,
            ),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "INVALID_ANCHOR_TIME"):
            self.store.conn.execute(
                "INSERT INTO label_anchors VALUES (?,?,?,?,?,?,?,?)",
                (
                    "lanch_" + "1" * 64,
                    interpretation_id,
                    "IMPULSE_START",
                    H4 * 2,
                    "LOW",
                    100,
                    H4 * 3,
                    "EXACT_BAR",
                ),
            )
        self.store.seal("label_groups", group_id)

    def test_schema_and_label_rows_are_immutable(self):
        _, task = self.make_task(study="schema")
        group = self.submit.submit(
            task_id=task.task_id,
            labeler_id="ali",
            request_key="schema-submit",
            kind="ABSTENTION",
            label_mode="RETROSPECTIVE",
            abstention_reason="unclear",
        )
        verify(self.store.root)
        for table in (
            "label_task_seeds",
            "label_tasks",
            "label_groups",
            "label_set_pins",
        ):
            if table == "label_set_pins":
                self.select.select(
                    task_id=task.task_id,
                    view_kind="RESEARCH",
                    as_of_us=group.submitted_at_us,
                    authorized_labelers=("ali",),
                    selector_policy_version="per-labeler-latest-v1",
                )
            column = self.store.conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchone()["name"]
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.conn.execute(f"UPDATE {table} SET {column}={column}")


if __name__ == "__main__":
    unittest.main()
