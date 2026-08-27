from atlas.agents.m15_channel import ChannelPolicy, M15ChannelEngine


def _mature(direction: str):
    e = M15ChannelEngine(ChannelPolicy())
    s = e.seed(permitted_direction=direction, fib_retracement_pct=100.0)
    if direction == "LONG":
        info = dict(channel_type="DESCENDING_CHANNEL", upper_boundary=1.1050, lower_boundary=1.1000,
                    reaction_highs=3, reaction_lows=3, upper_slope=-0.0010, lower_slope=-0.0011, stop_anchor=1.0997)
    else:
        info = dict(channel_type="ASCENDING_CHANNEL", upper_boundary=1.1050, lower_boundary=1.1000,
                    reaction_highs=3, reaction_lows=3, upper_slope=0.0010, lower_slope=0.0011, stop_anchor=1.1053)
    return e, e.register_pattern(s, info)


def test_descending_channel_lower_boundary_bullish_rejection_triggers_long():
    e, s = _mature("LONG")
    s = e.update_bar(s, dict(time="t", open=1.1001, high=1.1008, low=1.0999, close=1.1006, atr=0.0010,
                             spread=0.0001, wick_stat=0.0002, tick_size=0.0001))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.last_reason_code == "CHANNEL_BOUNDARY_REJECTION_VALID_TRIGGER"
    assert s.entry_reference == 1.1006
    assert s.final_stop < s.raw_stop_anchor


def test_ascending_channel_upper_boundary_bearish_rejection_triggers_short():
    e, s = _mature("SHORT")
    s = e.update_bar(s, dict(time="t", open=1.1049, high=1.1051, low=1.1042, close=1.1044, atr=0.0010,
                             spread=0.0001, wick_stat=0.0002, tick_size=0.0001))
    assert s.pattern_state == "VALID_TRIGGER"
    assert s.last_reason_code == "CHANNEL_BOUNDARY_REJECTION_VALID_TRIGGER"
    assert s.entry_reference == 1.1044
    assert s.final_stop > s.raw_stop_anchor


def test_channel_policy_has_no_breakout_mode():
    assert not hasattr(ChannelPolicy(), "entry_mode")

def test_channel_engine_has_no_retest_api():
    assert not hasattr(M15ChannelEngine(), "register_retest")
