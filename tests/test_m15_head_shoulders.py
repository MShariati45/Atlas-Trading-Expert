from atlas.agents.m15_head_shoulders import HeadShouldersPolicy, M15HeadShouldersEngine


def bar(close, time="b", atr=0.0010):
    return {
        "close": close,
        "time": time,
        "atr": atr,
        "spread": 0.00008,
        "wick_stat": 0.00030,
        "tick_size": 0.00001,
    }


def hs_candidate(e, entry_model="BREAKOUT"):
    e.policy.entry_model = entry_model
    s = e.seed(permitted_direction="SHORT", prior_trend="BULLISH", fib_retracement_pct=50.0)
    e.register_pattern(s, {
        "pattern_type": "HEAD_SHOULDERS",
        "left_shoulder": 1.1080,
        "head": 1.1110,
        "right_shoulder": 1.1076,
        "neckline": 1.1030,
        "atr": 0.0010,
    })
    return s


def inverse_candidate(e, entry_model="BREAKOUT"):
    e.policy.entry_model = entry_model
    s = e.seed(permitted_direction="LONG", prior_trend="BEARISH", fib_retracement_pct=52.0)
    e.register_pattern(s, {
        "pattern_type": "INVERSE_HEAD_SHOULDERS",
        "left_shoulder": 1.0920,
        "head": 1.0890,
        "right_shoulder": 1.0923,
        "neckline": 1.0970,
        "atr": 0.0010,
    })
    return s


def test_head_shoulders_sleeps_below_38_2_fib():
    e = M15HeadShouldersEngine()
    s = e.seed(permitted_direction="SHORT", prior_trend="BULLISH", fib_retracement_pct=30.0)
    assert s.pattern_state == "INACTIVE"


def test_valid_head_shoulders_requires_prior_uptrend_and_short_permission():
    e = M15HeadShouldersEngine()
    s = hs_candidate(e)
    assert s.pattern_state == "MATURE"
    assert s.pattern_type == "HEAD_SHOULDERS"


def test_neckline_close_confirms_breakout_entry_without_extra_sr_rule():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="BREAKOUT"))
    s = hs_candidate(e, "BREAKOUT")
    e.update_bar(s, bar(1.1027, time="break"))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.entry_reference == 1.1027
    assert s.final_stop > s.raw_stop_anchor
    assert "NECKLINE_BREAK_VALID_TRIGGER" in s.last_reason_code


def test_confirmation_candle_mode_waits_one_more_close():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="CONFIRMATION_CANDLE"))
    s = hs_candidate(e, "CONFIRMATION_CANDLE")
    e.update_bar(s, bar(1.1027, time="break"))
    assert s.pattern_state == "WAITING_CONFIRMATION_CANDLE"
    assert s.entry_reference is None
    e.update_bar(s, bar(1.1025, time="confirm"))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.entry_reference == 1.1025


def test_confirmation_candle_close_back_inside_marks_false_break():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="CONFIRMATION_CANDLE"))
    s = hs_candidate(e, "CONFIRMATION_CANDLE")
    e.update_bar(s, bar(1.1027, time="break"))
    e.update_bar(s, bar(1.1031, time="failed"))
    assert s.pattern_state == "INVALIDATED"
    assert "FALSE_BREAK" in s.last_reason_code


def test_retest_mode_uses_validated_retest_pivot_as_tighter_structural_anchor():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="RETEST"))
    s = hs_candidate(e, "RETEST")
    e.update_bar(s, bar(1.1027, time="break"))
    assert s.pattern_state == "WAITING_RETEST"
    e.register_retest(s, {
        "held": True,
        "rejected": True,
        "retest_pivot": 1.1034,
        "entry_reference": 1.1024,
        "time": "retest",
        "atr": 0.0010,
        "spread": 0.00008,
        "wick_stat": 0.00030,
        "tick_size": 0.00001,
    })
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.raw_stop_anchor == 1.1034
    assert s.final_stop > 1.1034


def test_large_breakout_is_not_chased_and_waits_for_retest():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="BREAKOUT", max_breakout_distance_atr=0.50))
    s = hs_candidate(e, "BREAKOUT")
    e.update_bar(s, bar(1.1018, time="extended", atr=0.0010))
    assert s.pattern_state == "WAITING_RETEST"
    assert s.entry_reference is None
    assert "TOO_EXTENDED" in s.last_reason_code


def test_inverse_head_shoulders_mirrors_long_stop_below_anchor():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="BREAKOUT"))
    s = inverse_candidate(e)
    assert s.pattern_state == "MATURE"
    e.update_bar(s, bar(1.0973, time="break"))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.final_stop < s.raw_stop_anchor


def test_excessive_shoulder_asymmetry_rejected():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(shoulder_tolerance_atr=0.30))
    s = e.seed(permitted_direction="SHORT", prior_trend="BULLISH", fib_retracement_pct=50.0)
    e.register_pattern(s, {
        "pattern_type": "HEAD_SHOULDERS",
        "left_shoulder": 1.1080,
        "head": 1.1120,
        "right_shoulder": 1.1070,
        "neckline": 1.1030,
        "atr": 0.0010,
    })
    assert s.pattern_state == "INVALIDATED"
    assert s.last_reason_code == "SHOULDER_ASYMMETRY_EXCESSIVE"

def test_valid_head_shoulders_trigger_expires_after_freshness_window():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="BREAKOUT", stale_after_bars=2))
    s = hs_candidate(e, "BREAKOUT")
    e.update_bar(s, bar(1.1027, time="break"))
    assert s.pattern_state == "VALID_TRIGGER"
    for i in range(3):
        e.update_bar(s, bar(1.1025 - i*0.0001, time=f"late{i}"))
    assert s.pattern_state == "STALE"
    assert s.last_reason_code == "HEAD_SHOULDERS_TRIGGER_STALE"

def test_head_shoulders_retest_trigger_starts_new_freshness_window():
    e = M15HeadShouldersEngine(HeadShouldersPolicy(entry_model="RETEST", stale_after_bars=2))
    s = hs_candidate(e, "RETEST")
    e.update_bar(s, bar(1.1027, time="break"))
    assert s.pattern_state == "WAITING_RETEST"
    e.update_bar(s, bar(1.1026, time="wait"))
    assert s.bars_since_breakout == 1
    e.register_retest(s, {"held": True, "rejected": True, "retest_pivot": 1.1031, "entry_reference": 1.1028, "time": "retest", "atr": 0.0010, "spread": 0.00008, "wick_stat": 0.00030, "tick_size": 0.00001})
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.bars_since_breakout == 0
