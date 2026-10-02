import unittest

from atlas2.evaluate.gates.h4_context import evaluate_h4_context


def source(
    group_id="lgrp_" + "a" * 64,
    *,
    trend="BULLISH",
    confidence=4,
    probability_ppm=900_000,
    kind="INTERPRETATIONS",
    is_sealed=True,
    is_causal=True,
    labeler_id="ali",
):
    primary = None if kind == "ABSTENTION" else {
        "rank": 1,
        "probability_ppm": probability_ppm,
        "trend": trend,
        "confidence": confidence,
        "correction_depth_ppm": 382_000,
        "correction_class": "MINOR",
        "reason": "fixture",
    }
    return {
        "group_id": group_id,
        "kind": kind,
        "labeler_id": labeler_id,
        "taint": 0,
        "primary": primary,
        "is_sealed": is_sealed,
        "is_causal": is_causal,
        "semantic": {
            "group_id": group_id,
            "kind": kind,
            "labeler_id": labeler_id,
            "primary": primary,
        },
    }


class H4ContextPolicyTests(unittest.TestCase):
    def evaluate(self, sources, *, direction="LONG", view="OPERATIONAL", policy="latest-authorized-owner-v1"):
        return evaluate_h4_context(
            tuple(sources),
            label_pin_present=True,
            pin_view_kind=view,
            selector_policy_version=policy,
            authorized_owner_labelers=("ali",),
            candidate_direction=direction,
        )

    def test_aligned_owner_direction_passes(self):
        result = self.evaluate((source(trend="BULLISH"),), direction="LONG")
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(result.reason_code, "H4_OWNER_DIRECTION_ALIGNED")

    def test_conflicting_owner_direction_fails(self):
        result = self.evaluate((source(trend="BEARISH"),), direction="LONG")
        self.assertEqual(result.outcome, "FAIL")
        self.assertEqual(result.reason_code, "H4_OWNER_DIRECTION_CONFLICT")

    def test_non_directional_owner_state_remains_not_evaluable(self):
        for trend in ("RANGE", "TRANSITION"):
            with self.subTest(trend=trend):
                result = self.evaluate((source(trend=trend),))
                self.assertEqual(result.outcome, "NOT_EVALUABLE")
                self.assertIn(trend, result.reason_code)

    def test_research_selector_or_non_owner_labeler_cannot_authorize_track_a(self):
        research = self.evaluate((source(),), view="RESEARCH")
        wrong_policy = self.evaluate((source(),), policy="per-labeler-latest-v1")
        wrong_labeler = self.evaluate((source(labeler_id="engine:reviewer"),))
        self.assertEqual(research.outcome, "NOT_EVALUABLE")
        self.assertEqual(research.reason_code, "H4_OWNER_OPERATIONAL_PIN_REQUIRED")
        self.assertEqual(wrong_policy.outcome, "NOT_EVALUABLE")
        self.assertEqual(wrong_policy.reason_code, "H4_OWNER_SELECTOR_REQUIRED")
        self.assertEqual(wrong_labeler.outcome, "NOT_EVALUABLE")
        self.assertEqual(wrong_labeler.reason_code, "H4_OWNER_LABELER_REQUIRED")

    def test_noncausal_unsealed_ambiguous_and_abstention_fail_closed(self):
        cases = (
            ((source(is_sealed=False),), "H4_LABEL_GROUP_UNSEALED"),
            ((source(is_causal=False),), "PINNED_H4_GROUP_NOT_CAUSAL"),
            (
                (
                    source("lgrp_" + "a" * 64),
                    source("lgrp_" + "b" * 64),
                ),
                "AMBIGUOUS_H4_LABEL_GROUPS",
            ),
            ((source(kind="ABSTENTION"),), "H4_LABEL_ABSTENTION"),
        )
        for sources, reason in cases:
            with self.subTest(reason=reason):
                result = self.evaluate(sources)
                self.assertEqual(result.outcome, "NOT_EVALUABLE")
                self.assertEqual(result.reason_code, reason)

    def test_missing_probability_is_not_invented(self):
        result = self.evaluate((source(probability_ppm=None),))
        names = {item["name"] for item in result.measurements}
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(names, {"owner_h4_confidence"})


if __name__ == "__main__":
    unittest.main()
