from atlas.agents.m15_flag_pennant import M15FlagPennantEngine


def bar(close, time="b", atr=0.0010):
    return {
        "close": close,
        "time": time,
        "atr": atr,
        "spread": 0.00008,
        "wick_stat": 0.00030,
        "tick_size": 0.00001,
    }


def test_flag_agent_has_early_access_below_38_2():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=22.0)
    assert s.discovery_allowed is True
    assert s.pattern_state == "SCANNING"


def test_new_flag_discovery_blocked_at_38_2():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=38.2)
    assert s.discovery_allowed is False
    assert s.pattern_state == "INACTIVE"
    e.register_flagpole(s, {"origin": 1.1000, "endpoint": 1.1040, "bars": 4, "atr": 0.0010})
    assert s.pattern_state == "INACTIVE"


def test_weak_flagpole_is_rejected():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=20.0)
    e.register_flagpole(s, {"origin": 1.1000, "endpoint": 1.1010, "bars": 4, "atr": 0.0010})
    assert s.pattern_state == "SCANNING"
    assert s.last_reason_code == "FLAGPOLE_TOO_WEAK"


def test_bull_flag_breakout_produces_structural_stop():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=20.0)
    e.register_flagpole(s, {"origin": 1.1000, "endpoint": 1.1040, "bars": 4, "atr": 0.0010})
    e.update_consolidation(s, {"high": 1.1035, "low": 1.1028, "bars": 4, "shape": "FLAG"})
    assert s.pattern_state == "MATURE"
    e.update_bar(s, bar(1.1037))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.pattern_type == "BULL_FLAG"
    assert s.final_stop < s.raw_stop_anchor
    assert s.projected_flagpole_target > s.entry_reference


def test_deep_consolidation_invalidates_flag():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=18.0)
    e.register_flagpole(s, {"origin": 1.1000, "endpoint": 1.1040, "bars": 4, "atr": 0.0010})
    e.update_consolidation(s, {"high": 1.1035, "low": 1.1020, "bars": 4, "shape": "FLAG"})
    assert s.pattern_state == "INVALIDATED"
    assert s.last_reason_code == "FLAG_CONSOLIDATION_TOO_DEEP"


def test_mature_flag_can_finish_after_fib_crosses_38_2():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=30.0)
    e.register_flagpole(s, {"origin": 1.1000, "endpoint": 1.1040, "bars": 4, "atr": 0.0010})
    e.update_consolidation(s, {"high": 1.1035, "low": 1.1028, "bars": 4, "shape": "PENNANT"})
    assert s.pattern_state == "MATURE"
    e.update_fib_context(s, 39.0)
    assert s.discovery_allowed is False
    assert s.mature_carryover_allowed is True
    assert s.pattern_state == "MATURE"
    e.update_bar(s, bar(1.1038, time="after38"))
    assert s.pattern_state == "VALID_TRIGGER"


def test_wrong_direction_flagpole_never_matures():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=20.0)
    e.register_flagpole(s, {"origin": 1.1040, "endpoint": 1.1000, "bars": 4, "atr": 0.0010})
    assert s.pattern_state == "SCANNING"
    assert s.last_reason_code == "FLAGPOLE_OPPOSITE_TO_HTF_PERMISSION"

def test_latched_recovery_below_38_2_does_not_reenable_new_flag_discovery():
    e = M15FlagPennantEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=45.0)
    assert s.discovery_allowed is False
    e.update_fib_context(s, 25.0, new_discovery_allowed=False)
    assert s.fib_retracement_pct == 25.0
    assert s.discovery_allowed is False
    assert s.pattern_state == "INACTIVE"
    e.register_flagpole(s, {"origin": 1.1000, "endpoint": 1.1040, "bars": 4, "atr": 0.0010})
    assert s.pattern_state == "INACTIVE"
    assert s.last_reason_code == "NEW_FLAG_DISCOVERY_BLOCKED_BY_FIB"
