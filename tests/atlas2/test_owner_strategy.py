import json
import unittest

from atlas2.strategy.owner_entry import (
    ATR_BUFFER_TEST_PPM,
    SOURCE_SHA256,
    STARTING_ATR_BUFFER_PPM,
    owner_entry_stop_policy,
    owner_track_a_strategy,
)


class OwnerStrategyContractTests(unittest.TestCase):
    def test_source_hash_and_master_boundary_are_frozen(self):
        policy = owner_entry_stop_policy()
        self.assertEqual(
            SOURCE_SHA256,
            "45a83b5c9f0dc6240143dfff1ca3e4a0c367c635e4ef2d8e77656cee32ec0e86",
        )
        self.assertFalse(policy["master_rule"]["fibonacci_is_entry_trigger"])
        self.assertFalse(
            policy["master_rule"]["forming_confirmation_candle_entry_allowed"]
        )
        unresolved = set(policy["unresolved_operational_details"])
        self.assertIn("MEANINGFUL_OR_VALID_SWING_DEFINITION", unresolved)
        self.assertIn("RETEST_HOLD_DEFINITION", unresolved)
        self.assertIn("REJECTION_CANDLE_QUALIFICATION", unresolved)
        self.assertIn("STRUCTURAL_LEVEL_IDENTIFICATION", unresolved)
    def test_pattern_specific_entry_rules_match_owner_source(self):
        patterns = owner_entry_stop_policy()["patterns"]
        self.assertEqual(
            patterns["CORRECTION_REVERSAL"]["LONG"]["entry"],
            "NEXT_M15_OPEN",
        )
        self.assertEqual(
            patterns["DIRECT_BREAKOUT"]["SHORT"]["entry"],
            "NEXT_M15_OPEN",
        )
        self.assertEqual(
            patterns["BREAKOUT_RETEST"]["LONG"]["entry"],
            "ABOVE_REJECTION_CANDLE_HIGH",
        )
        self.assertEqual(patterns["FLAG"]["LONG"]["entry"], "NEXT_CANDLE")
        self.assertEqual(
            patterns["HORIZONTAL_RANGE"]["SHORT"]["entry"], "NEXT_CANDLE"
        )

    def test_stop_buffer_variants_are_research_only(self):
        policy = owner_entry_stop_policy()
        buffer_rule = policy["atr14_buffer"]
        self.assertEqual(ATR_BUFFER_TEST_PPM, (0, 100_000, 200_000))
        self.assertEqual(STARTING_ATR_BUFFER_PPM, 100_000)
        self.assertEqual(buffer_rule["final_selection"], "PER_INSTRUMENT_BACKTEST")
    def test_track_a_baseline_is_shadow_only_and_deterministic(self):
        first = owner_track_a_strategy()
        second = owner_track_a_strategy()
        self.assertEqual(first, second)
        self.assertEqual(first.strategy_key, "OWNER_TRACK_A")
        plan = json.loads(first.plan_json)
        self.assertEqual(plan["execution"], "NONE")
        self.assertTrue(plan["research_only"])
        self.assertEqual(plan["target_r_micro"], 2_000_000)
        self.assertTrue(plan["break_even_enabled"])
        self.assertEqual(plan["break_even_trigger_r_micro"], 1_400_000)
        self.assertEqual(plan["atr14_buffer_ppm"], 100_000)

        roles = {
            item["gate_kind"]: item["role"]
            for item in json.loads(first.gate_roles_json)
        }
        self.assertEqual(roles["CORRECTION_LOCATION"], "INFORMATIONAL")
        self.assertEqual(roles["H1_CONTEXT"], "INFORMATIONAL")
        self.assertEqual(roles["M15_COORDINATION"], "REQUIRED")
        self.assertIn("20261002v1", first.version)
    def test_no_be_ablation_and_buffer_variants_get_distinct_versions(self):
        baseline = owner_track_a_strategy()
        no_be = owner_track_a_strategy(break_even_enabled=False)
        wider = owner_track_a_strategy(atr_buffer_ppm=200_000)
        self.assertNotEqual(baseline.strategy_version_id, no_be.strategy_version_id)
        self.assertNotEqual(baseline.strategy_version_id, wider.strategy_version_id)
        self.assertIsNone(json.loads(no_be.plan_json)["break_even_trigger_r_micro"])

    def test_unapproved_buffer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "owner-approved research value"):
            owner_track_a_strategy(atr_buffer_ppm=150_000)


if __name__ == "__main__":
    unittest.main()
