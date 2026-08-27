from atlas.agents.h4_structure import PricePoint
from atlas.agents.m15_impulse_correction import M15BufferPolicy, M15ImpulseCorrectionEngine


def bar(t, high, low, close, spread=0.00008, atr=0.0010, wick=0.00030, tick=0.00001):
    return {
        "time": t,
        "high": high,
        "low": low,
        "close": close,
        "spread": spread,
        "atr": atr,
        "wick_stat": wick,
        "tick_size": tick,
    }


def test_choch_is_not_a_trade_trigger():
    e = M15ImpulseCorrectionEngine()
    s = e.seed(
        trend="BEARISH",
        control_pivot=PricePoint(1.1050, "lh"),
        endpoint=PricePoint(1.1000, "ll"),
        permitted_direction="LONG",
    )
    e.update(s, bar("c1", 1.1060, 1.1010, 1.1055))
    assert s.phase == "BULLISH_REVERSAL_CANDIDATE"
    assert s.trigger_entry_reference is None
    assert s.last_reason_code == "BULLISH_CHOCH_CONFIRMED"


def test_bullish_reversal_requires_hl_then_bos():
    e = M15ImpulseCorrectionEngine()
    s = e.seed(
        trend="BEARISH",
        control_pivot=PricePoint(1.1050, "lh"),
        endpoint=PricePoint(1.1000, "ll"),
        permitted_direction="LONG",
    )
    e.update(s, bar("c1", 1.1060, 1.1010, 1.1055))  # CHoCH
    e.update(s, bar("c2", 1.1080, 1.1055, 1.1075))  # HH extends
    assert s.phase == "BULLISH_REVERSAL_CANDIDATE"
    e.update(s, bar("c3", 1.1070, 1.1045, 1.1050))  # meaningful pullback -> HL
    assert s.phase == "BULLISH_PULLBACK_FORMING"
    assert s.candidate_reversal_pivot is not None
    hh = s.new_extreme.price
    e.update(s, bar("c4", hh + 0.0010, 1.1050, hh + 0.0005))  # BOS close
    assert s.phase == "VALID_TRIGGER"
    assert s.trend == "BULLISH"
    assert s.final_stop < s.raw_stop_anchor
    assert s.trigger_entry_reference is not None


def test_bearish_reversal_requires_lh_then_bos():
    e = M15ImpulseCorrectionEngine()
    s = e.seed(
        trend="BULLISH",
        control_pivot=PricePoint(1.1950, "hl"),
        endpoint=PricePoint(1.2000, "hh"),
        permitted_direction="SHORT",
    )
    e.update(s, bar("c1", 1.1990, 1.1940, 1.1945))  # CHoCH
    e.update(s, bar("c2", 1.1945, 1.1920, 1.1925))  # LL extends
    e.update(s, bar("c3", 1.1960, 1.1930, 1.1950))  # meaningful pullback -> LH
    assert s.phase == "BEARISH_PULLBACK_FORMING"
    ll = s.new_extreme.price
    e.update(s, bar("c4", 1.1950, ll - 0.0010, ll - 0.0005))
    assert s.phase == "VALID_TRIGGER"
    assert s.trend == "BEARISH"
    assert s.final_stop > s.raw_stop_anchor


def test_symbol_aware_buffer_uses_largest_component():
    policy = M15BufferPolicy(spread_multiplier=2.0, atr_fraction=0.1, wick_fraction=0.5, min_tick_multiple=2.0)
    e = M15ImpulseCorrectionEngine(policy)
    b = bar("x", 1.0, 0.9, 0.95, spread=0.00010, atr=0.0010, wick=0.00080, tick=0.00001)
    assert e._buffer(b) == 0.00040  # wick component dominates


def test_wrong_htf_permission_invalidates_reversal_candidate():
    e = M15ImpulseCorrectionEngine()
    s = e.seed(
        trend="BEARISH",
        control_pivot=PricePoint(1.1050, "lh"),
        endpoint=PricePoint(1.1000, "ll"),
        permitted_direction="SHORT",
    )
    e.update(s, bar("c1", 1.1060, 1.1010, 1.1055))
    assert s.phase == "INVALIDATED"
    assert s.last_reason_code == "CHOCH_OPPOSITE_TO_HTF_PERMISSION"


def test_valid_trigger_becomes_stale_after_configured_bars():
    e = M15ImpulseCorrectionEngine(M15BufferPolicy(stale_after_bars=2))
    s = e.seed(
        trend="BEARISH",
        control_pivot=PricePoint(1.1050, "lh"),
        endpoint=PricePoint(1.1000, "ll"),
        permitted_direction="LONG",
    )
    e.update(s, bar("c1", 1.1060, 1.1010, 1.1055))
    e.update(s, bar("c2", 1.1080, 1.1055, 1.1075))
    e.update(s, bar("c3", 1.1070, 1.1045, 1.1050))
    hh = s.new_extreme.price
    e.update(s, bar("c4", hh + 0.0010, 1.1050, hh + 0.0005))
    assert s.phase == "VALID_TRIGGER"
    e.update(s, bar("c5", 1.1100, 1.1080, 1.1090))
    e.update(s, bar("c6", 1.1110, 1.1090, 1.1100))
    e.update(s, bar("c7", 1.1120, 1.1100, 1.1110))
    assert s.phase == "STALE"
