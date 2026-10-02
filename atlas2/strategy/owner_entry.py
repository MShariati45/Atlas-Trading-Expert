"""Owner-approved P1 entry and stop-loss contract."""
from __future__ import annotations

from atlas2.model.evaluation import StrategyVersion

SOURCE_SHA256 = "45a83b5c9f0dc6240143dfff1ca3e4a0c367c635e4ef2d8e77656cee32ec0e86"
ENTRY_STOP_POLICY_KEY = "ATLAS_OWNER_ENTRY_STOPLOSS"
ENTRY_STOP_POLICY_VERSION = "2026-10-02-v1"

ATR_BUFFER_TEST_PPM = (0, 100_000, 200_000)
STARTING_ATR_BUFFER_PPM = 100_000

_OWNER_GATE_ROLES = (
    ("DATA_QUALITY", "REQUIRED"),
    ("M15_COORDINATION", "REQUIRED"),
    ("H4_CONTEXT", "REQUIRED"),
    ("H1_CONTEXT", "INFORMATIONAL"),
    ("CORRECTION_LOCATION", "INFORMATIONAL"),
    ("SESSION_DAY", "REQUIRED"),
    ("NEWS_RISK", "REQUIRED"),
    ("SPREAD_COST", "REQUIRED"),
)

def owner_entry_stop_policy() -> dict:
    """Return the source-grounded P1 entry/SL policy as fresh data."""
    return {
        "policy_key": ENTRY_STOP_POLICY_KEY,
        "policy_version": ENTRY_STOP_POLICY_VERSION,
        "source_sha256": SOURCE_SHA256,
        "timeframe": "M15",
        "master_rule": {
            "trigger_authority": "M15_PATTERN",
            "invalidation_authority": "M15_PATTERN",
            "context_authority": "H4_FIBONACCI",
            "fibonacci_is_entry_trigger": False,
            "forming_confirmation_candle_entry_allowed": False,
        },
        "patterns": {
            "CORRECTION_REVERSAL": {
                "LONG": {
                    "confirmation": "M15_CLOSE_ABOVE_LAST_MEANINGFUL_CORRECTIVE_LOWER_HIGH",
                    "entry": "NEXT_M15_OPEN",
                    "stop": "BELOW_FINAL_CORRECTION_SWING_LOW",
                },
                "SHORT": {
                    "confirmation": "M15_CLOSE_BELOW_LAST_MEANINGFUL_CORRECTIVE_HIGHER_LOW",
                    "entry": "NEXT_M15_OPEN",
                    "stop": "ABOVE_FINAL_CORRECTION_SWING_HIGH",
                },
            },

            "DIRECT_BREAKOUT": {
                "LONG": {
                    "confirmation": "M15_CLOSE_ABOVE_STRUCTURAL_RESISTANCE_OR_RANGE_BOUNDARY",
                    "entry": "NEXT_M15_OPEN",
                    "stop": "BELOW_LAST_MEANINGFUL_PRE_BREAKOUT_SWING_LOW",
                },
                "SHORT": {
                    "confirmation": "M15_CLOSE_BELOW_STRUCTURAL_SUPPORT",
                    "entry": "NEXT_M15_OPEN",
                    "stop": "ABOVE_LAST_MEANINGFUL_PRE_BREAKDOWN_SWING_HIGH",
                },
            },
            "BREAKOUT_RETEST": {
                "LONG": {
                    "confirmation": "BROKEN_LEVEL_RETEST_HELD_THEN_COMPLETED_BULLISH_REJECTION",
                    "entry": "ABOVE_REJECTION_CANDLE_HIGH",
                    "stop": "BELOW_RETEST_SWING_LOW",
                },
                "SHORT": {
                    "confirmation": "BROKEN_LEVEL_RETEST_HELD_THEN_COMPLETED_BEARISH_REJECTION",
                    "entry": "BELOW_REJECTION_CANDLE_LOW",
                    "stop": "ABOVE_RETEST_SWING_HIGH",
                },
            },

            "FLAG": {
                "LONG": {
                    "confirmation": "M15_CLOSE_ABOVE_UPPER_FLAG_BOUNDARY",
                    "entry": "NEXT_CANDLE",
                    "stop": "BELOW_MEANINGFUL_FLAG_SWING_LOW",
                },
                "SHORT": {
                    "confirmation": "M15_CLOSE_BELOW_LOWER_FLAG_BOUNDARY",
                    "entry": "NEXT_CANDLE",
                    "stop": "ABOVE_MEANINGFUL_FLAG_SWING_HIGH",
                },
            },
            "HORIZONTAL_RANGE": {
                "LONG": {
                    "confirmation": "M15_CLOSE_ABOVE_RANGE_RESISTANCE",
                    "entry": "NEXT_CANDLE",
                    "stop": "BELOW_LAST_VALID_INTERNAL_SWING_LOW_THAT_LAUNCHED_BREAKOUT",
                },
                "SHORT": {
                    "confirmation": "M15_CLOSE_BELOW_RANGE_SUPPORT",
                    "entry": "NEXT_CANDLE",
                    "stop": "ABOVE_LAST_VALID_INTERNAL_SWING_HIGH",
                },
            },
        },

        "structural_level_rule": (
            "USE_PATTERN_STRUCTURE_NOT_ARBITRARY_PRICE_OR_FIBONACCI_LEVEL"
        ),
        "stop_rule": {
            "long": "BEYOND_RELEVANT_STRUCTURAL_LOW",
            "short": "BEYOND_RELEVANT_STRUCTURAL_HIGH",
            "tighten_to_manufacture_2R": False,
        },
        "atr14_buffer": {
            "preferred": True,
            "research_values_ppm": list(ATR_BUFFER_TEST_PPM),
            "starting_test_ppm": STARTING_ATR_BUFFER_PPM,
            "final_selection": "PER_INSTRUMENT_BACKTEST",
        },
        "two_r_rule": {
            "target_r_micro": 2_000_000,
            "structural_entry_and_stop_first": True,
            "reject_if_2r_not_realistically_available": True,
        },
        "unresolved_operational_details": [
            "BREAKOUT_RETEST_EXACT_TRIGGER_OFFSET_OR_FILL_RULE",
            "FLAG_NEXT_CANDLE_EXACT_FILL_PRICE",
            "HORIZONTAL_RANGE_NEXT_CANDLE_EXACT_FILL_PRICE",
            "MEANINGFUL_OR_VALID_SWING_DEFINITION",
            "RETEST_HOLD_DEFINITION",
            "REJECTION_CANDLE_QUALIFICATION",
            "STRUCTURAL_LEVEL_IDENTIFICATION",
            "TWO_R_REALISTIC_AVAILABILITY_TEST",
            "FINAL_ATR_BUFFER_PER_INSTRUMENT",
        ],
    }

def owner_track_a_strategy(
    *, break_even_enabled: bool = True, atr_buffer_ppm: int = STARTING_ATR_BUFFER_PPM
) -> StrategyVersion:
    """Create the P1 Track A research strategy version; execution remains NONE."""
    if type(break_even_enabled) is not bool:
        raise ValueError("break_even_enabled must be bool")
    if atr_buffer_ppm not in ATR_BUFFER_TEST_PPM:
        raise ValueError("atr_buffer_ppm must be an owner-approved research value")

    suffix = "BE14" if break_even_enabled else "NO_BE"
    buffer_tag = f"ATR{atr_buffer_ppm:06d}"
    policy_tag = ENTRY_STOP_POLICY_VERSION.replace("-", "")
    return StrategyVersion.create(
        strategy_key="OWNER_TRACK_A",
        version=f"v1-{policy_tag}-{suffix}-{buffer_tag}",
        gate_roles=[
            {"gate_kind": gate_kind, "role": role}
            for gate_kind, role in _OWNER_GATE_ROLES
        ],
        plan={
            "execution": "NONE",
            "entry_stop_policy": owner_entry_stop_policy(),
            "atr14_buffer_ppm": atr_buffer_ppm,
            "target_r_micro": 2_000_000,
            "break_even_enabled": break_even_enabled,
            "break_even_trigger_r_micro": 1_400_000 if break_even_enabled else None,
            "research_only": True,
        },
    )
