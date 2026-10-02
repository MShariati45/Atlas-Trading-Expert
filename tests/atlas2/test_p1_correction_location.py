import unittest

from atlas2.evaluate.gates.correction_location import evaluate_correction_location


def source(group_id="lgrp_" + "a" * 64, *, kind="INTERPRETATIONS", depth=382_000):
    primary = None if kind == "ABSTENTION" else {
        "rank": 1,
        "probability_ppm": 1_000_000,
        "trend": "BULLISH",
        "confidence": 4,
        "correction_depth_ppm": depth,
        "correction_class": "MINOR",
        "reason": "fixture",
    }
    return {
        "group_id": group_id,
        "kind": kind,
        "taint": 0,
        "primary": primary,
        "semantic": {
            "group_id": group_id,
            "kind": kind,
            "primary": primary,
        },
    }


class CorrectionLocationPolicyTests(unittest.TestCase):
    def test_no_pin_is_explicitly_unavailable(self):
        result = evaluate_correction_location((), label_pin_present=False)
        self.assertEqual(result.reason_code, "NO_LABEL_PIN")
        self.assertEqual(result.measurements, ())

    def test_one_pinned_source_measures_depth(self):
        result = evaluate_correction_location(
            (source(),), label_pin_present=True
        )
        self.assertEqual(result.reason_code, "H4_CORRECTION_DEPTH_MEASURED")
        self.assertEqual(
            result.measurements,
            ({"name": "correction_depth_ppm", "value": 382_000, "unit": "ppm"},),
        )

    def test_multiple_sources_fail_closed_without_aggregation_rule(self):
        result = evaluate_correction_location(
            (
                source("lgrp_" + "a" * 64),
                source("lgrp_" + "b" * 64),
            ),
            label_pin_present=True,
        )
        self.assertEqual(result.reason_code, "AMBIGUOUS_H4_LABEL_GROUPS")
        self.assertEqual(result.measurements, ())

    def test_abstention_and_missing_depth_remain_measurement_only(self):
        abstain = evaluate_correction_location(
            (source(kind="ABSTENTION"),), label_pin_present=True
        )
        missing = evaluate_correction_location(
            (source(depth=None),), label_pin_present=True
        )
        self.assertEqual(abstain.reason_code, "H4_LABEL_ABSTENTION")
        self.assertEqual(missing.reason_code, "H4_CORRECTION_DEPTH_UNAVAILABLE")
        self.assertEqual(abstain.measurements, ())
        self.assertEqual(missing.measurements, ())


if __name__ == "__main__":
    unittest.main()
