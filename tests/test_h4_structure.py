from atlas.agents.h4_structure import H4StructureAgent, PricePoint
from atlas.core.events import Event


def bar(t, high, low, close):
    return Event(type="H4_BAR_CLOSED", symbol="EURUSD", payload={"time": t, "high": high, "low": low, "close": close})


def seeded_bullish():
    a = H4StructureAgent()
    a.seed("EURUSD", trend="BULLISH", origin=PricePoint(100, "A"), endpoint=PricePoint(120, "B"), control_pivot=PricePoint(100, "A"))
    return a


def test_bearish_candle_does_not_create_new_impulse():
    a = seeded_bullish()
    r = a.handle(bar("C1", 119, 116, 117))
    assert r.data["trend"] == "BULLISH"
    assert r.data["strategic_origin"]["price"] == 100
    assert r.data["strategic_endpoint"]["price"] == 120
    assert r.data["phase"] == "BULLISH_IMPULSE"
    assert r.reason_codes == ["INTERNAL_PULLBACK_LT_38_2"]


def test_multiple_shallow_bars_remain_one_strategic_impulse():
    a = seeded_bullish()
    for i, (h, l, c) in enumerate([(119, 117, 118), (118, 115, 116), (119, 116, 118)], 1):
        r = a.handle(bar(f"C{i}", h, l, c))
    assert r.data["strategic_origin"]["price"] == 100
    assert r.data["strategic_endpoint"]["price"] == 120
    assert r.data["correction_depth"] < 0.382
    assert r.data["phase"] == "BULLISH_IMPULSE"


def test_38_2_correction_becomes_strategic_candidate_not_reversal():
    a = seeded_bullish()
    r = a.handle(bar("C1", 119, 112, 114))
    assert r.data["trend"] == "BULLISH"
    assert r.data["phase"] == "BULLISH_CORRECTION"
    assert r.data["correction_qualified"] is True
    assert r.reason_codes == ["STRATEGIC_CORRECTION_QUALIFIED"]


def test_control_pivot_close_break_creates_reversal_candidate_not_immediate_bearish():
    a = H4StructureAgent()
    a.seed("EURUSD", trend="BULLISH", origin=PricePoint(100, "A"), endpoint=PricePoint(120, "B"), control_pivot=PricePoint(108, "HL"))
    r = a.handle(bar("C1", 111, 105, 107))
    assert r.data["trend"] == "BULLISH"
    assert r.data["phase"] == "BULLISH_REVERSAL_CANDIDATE"
    assert r.reason_codes == ["CONTROL_PIVOT_CLOSE_BREAK"]


def test_new_high_extends_endpoint_without_resetting_origin():
    a = seeded_bullish()
    r = a.handle(bar("C1", 123, 118, 122))
    assert r.data["strategic_endpoint"]["price"] == 123
    assert r.data["strategic_origin"]["price"] == 100
    assert r.data["phase"] == "BULLISH_IMPULSE"

from atlas.agents.h4_structure import TrendlineAnchor


def h4_bar(t, open_, high, low, close):
    return Event(type="H4_BAR_CLOSED", symbol="EURUSD", payload={"time": t, "open": open_, "high": high, "low": low, "close": close})


def test_bearish_trendline_break_needs_confirmation_candle_before_early_bullish():
    a = H4StructureAgent()
    a.seed(
        "EURUSD",
        trend="BEARISH",
        origin=PricePoint(120, "2026-06-01T00:00:00+00:00"),
        endpoint=PricePoint(100, "2026-06-10T00:00:00+00:00"),
        control_pivot=PricePoint(120, "2026-06-01T00:00:00+00:00"),
    )
    a.configure_trendline("EURUSD", [
        TrendlineAnchor(118, "2026-06-01T00:00:00+00:00", "HIGH"),
        TrendlineAnchor(112, "2026-06-05T00:00:00+00:00", "HIGH"),
    ])
    first = a.handle(h4_bar("2026-06-09T00:00:00+00:00", 106, 109, 104, 108))
    assert first.data["trend"] == "BEARISH"
    assert first.data["trendline"]["status"] == "BREAKOUT_PENDING"
    assert first.data["effective_direction"] == "BEARISH"
    second = a.handle(h4_bar("2026-06-09T04:00:00+00:00", 108, 111, 107, 110))
    assert second.data["trend"] == "BEARISH"  # formal trend is preserved
    assert second.data["trendline"]["status"] == "RETIRED"
    assert second.data["trendline"]["early_direction"] == "BULLISH"
    assert second.data["effective_direction"] == "BULLISH"
    assert "H4_TRENDLINE_REVERSAL_CONFIRMED" in [x["reason_code"] for x in second.data["audit"]]


def test_three_trendline_touches_are_strong_quality():
    a = H4StructureAgent()
    a.seed(
        "EURUSD", trend="BEARISH",
        origin=PricePoint(120, "2026-06-01T00:00:00+00:00"),
        endpoint=PricePoint(100, "2026-06-10T00:00:00+00:00"),
        control_pivot=PricePoint(120, "2026-06-01T00:00:00+00:00"),
    )
    a.configure_trendline("EURUSD", [
        TrendlineAnchor(118, "2026-06-01T00:00:00+00:00", "HIGH"),
        TrendlineAnchor(115, "2026-06-03T00:00:00+00:00", "HIGH"),
        TrendlineAnchor(112, "2026-06-05T00:00:00+00:00", "HIGH"),
    ])
    raw = a.store.get(a._key("EURUSD"))
    assert raw["trendline"]["touch_count"] == 3
    assert raw["trendline"]["quality"] == "STRONG"


def test_bullish_trendline_break_mirrors_to_early_bearish():
    a = H4StructureAgent()
    a.seed(
        "EURUSD",
        trend="BULLISH",
        origin=PricePoint(100, "2026-06-01T00:00:00+00:00"),
        endpoint=PricePoint(120, "2026-06-10T00:00:00+00:00"),
        control_pivot=PricePoint(100, "2026-06-01T00:00:00+00:00"),
    )
    a.configure_trendline("EURUSD", [
        TrendlineAnchor(102, "2026-06-01T00:00:00+00:00", "LOW"),
        TrendlineAnchor(108, "2026-06-05T00:00:00+00:00", "LOW"),
    ])
    one = a.handle(h4_bar("2026-06-09T00:00:00+00:00", 114, 115, 110, 111))
    assert one.data["trendline"]["status"] == "BREAKOUT_PENDING"
    two = a.handle(h4_bar("2026-06-09T04:00:00+00:00", 111, 112, 108, 109))
    assert two.data["trend"] == "BULLISH"
    assert two.data["effective_direction"] == "BEARISH"
