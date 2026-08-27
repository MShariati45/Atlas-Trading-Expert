from atlas.agents.m15_triangle_wedge import M15TriangleWedgeEngine


def bar(close, time="b", atr=0.0010):
    return {
        "close": close,
        "time": time,
        "atr": atr,
        "spread": 0.00008,
        "wick_stat": 0.00030,
        "tick_size": 0.00001,
    }


def mature_long(e, fib=50.0):
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=fib)
    e.register_pattern(s, {
        "pattern_type": "SYMMETRICAL_TRIANGLE",
        "upper_boundary": 1.1050,
        "lower_boundary": 1.1010,
        "reaction_highs": 3,
        "reaction_lows": 3,
        "first_structural_sr": 1.1060,
        "stop_anchor": 1.1020,
    })
    return s


def test_triangle_agent_waits_for_38_2_activation():
    e = M15TriangleWedgeEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=30.0)
    assert s.pattern_state == "INACTIVE"


def test_pattern_requires_meaningful_reaction_pivots():
    e = M15TriangleWedgeEngine()
    s = e.seed(permitted_direction="LONG", fib_retracement_pct=48.0)
    e.register_pattern(s, {
        "pattern_type": "ASCENDING_TRIANGLE",
        "upper_boundary": 1.1050,
        "lower_boundary": 1.1010,
        "reaction_highs": 1,
        "reaction_lows": 2,
        "first_structural_sr": 1.1060,
    })
    assert s.pattern_state == "FORMING"
    assert s.last_reason_code == "INSUFFICIENT_MEANINGFUL_REACTION_PIVOTS"


def test_boundary_break_alone_is_never_trade_trigger():
    e = M15TriangleWedgeEngine()
    s = mature_long(e)
    e.update_bar(s, bar(1.1055, time="boundary"))
    assert s.pattern_state == "WAITING_FOR_FIRST_SR_BREAK"
    assert s.entry_reference is None
    assert s.last_reason_code == "BOUNDARY_BREAK_CONFIRMED"


def test_first_resistance_break_completes_bullish_trigger():
    e = M15TriangleWedgeEngine()
    s = mature_long(e)
    e.update_bar(s, bar(1.1055, time="boundary"))
    e.update_bar(s, bar(1.1062, time="sr"))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.entry_reference == 1.1062
    assert s.final_stop < s.raw_stop_anchor
    assert "STRUCTURAL_BREAK_VALID_TRIGGER" in s.last_reason_code


def test_one_strong_candle_may_clear_both_hard_gates():
    e = M15TriangleWedgeEngine()
    s = mature_long(e)
    e.update_bar(s, bar(1.1063, time="both"))
    assert s.pattern_state == "VALID_TRIGGER"


def test_close_back_inside_before_sr_break_invalidates_false_break():
    e = M15TriangleWedgeEngine()
    s = mature_long(e)
    e.update_bar(s, bar(1.1055, time="boundary"))
    e.update_bar(s, bar(1.1048, time="failed"))
    assert s.pattern_state == "INVALIDATED"
    assert s.last_reason_code == "FALSE_BREAK_CLOSE_BACK_INSIDE_PATTERN"


def test_bearish_wedge_requires_support_break_and_stop_above_anchor():
    e = M15TriangleWedgeEngine()
    s = e.seed(permitted_direction="SHORT", fib_retracement_pct=55.0)
    e.register_pattern(s, {
        "pattern_type": "RISING_WEDGE",
        "upper_boundary": 1.1100,
        "lower_boundary": 1.1060,
        "reaction_highs": 3,
        "reaction_lows": 2,
        "first_structural_sr": 1.1050,
        "stop_anchor": 1.1090,
    })
    assert s.pattern_state == "MATURE"
    e.update_bar(s, bar(1.1057, time="boundary"))
    assert s.pattern_state == "WAITING_FOR_FIRST_SR_BREAK"
    e.update_bar(s, bar(1.1048, time="support"))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.final_stop > s.raw_stop_anchor
