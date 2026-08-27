from atlas.agents.h1_structure import H1StructureAgent
from atlas.agents.h4_structure import PricePoint
from atlas.core.events import Event


def bar(t, high, low, close, **extra):
    payload={"time":t,"high":high,"low":low,"close":close,**extra}
    return Event(type="H1_BAR_CLOSED", symbol="EURUSD", payload=payload)


def seeded():
    a=H1StructureAgent()
    a.seed("EURUSD", trend="BULLISH", origin=PricePoint(100,"A"), endpoint=PricePoint(120,"B"), control_pivot=PricePoint(100,"A"))
    return a


def test_h1_shallow_multicandle_leg_preserved_without_cross_timeframe_fields():
    a=seeded()
    for i,(h,l,c) in enumerate([(119,117,118),(118,115,116),(119,116,118)],1):
        r=a.handle(bar(f"C{i}",h,l,c))
    assert r.data["trend"]=="BULLISH"
    assert r.data["strategic_origin"]["price"]==100
    assert r.data["correction_depth"] < 0.382
    assert "h4_trend" not in r.data
    assert "h4_relationship" not in r.data
    assert "fib_eligible" not in r.data
    assert "m15_eligible" not in r.data
    assert "trendline" not in r.data


def test_h1_38_2_correction_is_h1_fact_only():
    a=seeded()
    r=a.handle(bar("C1",119,112,114))
    assert r.data["correction_depth"] >= 0.382
    assert r.data["correction_qualified"] is True
    assert r.data["phase"]=="BULLISH_CORRECTION"


def test_h1_rejects_h4_information_in_input():
    a=seeded()
    r=a.handle(bar("C1",119,115,117,h4_trend="BULLISH"))
    assert r.status=="REJECTED_INPUT"
    assert "H1_CROSS_TIMEFRAME_INPUT_FORBIDDEN" in r.reason_codes


def test_h1_can_be_bearish_independently():
    a=H1StructureAgent()
    a.seed("EURUSD", trend="BEARISH", origin=PricePoint(120,"A"), endpoint=PricePoint(100,"B"), control_pivot=PricePoint(120,"A"))
    r=a.handle(bar("C1",105,99,101))
    assert r.data["trend"]=="BEARISH"


def test_h1_rolls_control_pivot_on_same_continuation_bos_bar():
    a=seeded()
    a.handle(bar("C1",119,112,114))  # >=38.2% correction
    r=a.handle(bar("C2",121,116,120.5))
    assert r.data["trend"]=="BULLISH"
    assert r.data["strategic_endpoint"]["price"]==121
    assert r.data["strategic_origin"]["price"]==112
    assert r.data["control_pivot"]["price"]==112
    assert r.reason_codes==["VALIDATED_BY_CONTINUATION_BOS"]


def test_h1_control_break_enters_persistent_reversal_candidate():
    a=seeded()
    r=a.handle(bar("C1",118,99,99.5))
    assert r.data["trend"]=="BULLISH"
    assert r.data["reversal_direction"]=="BEARISH"
    assert r.data["phase"]=="BEARISH_REVERSAL_CANDIDATE"
    r=a.handle(bar("C2",105,98,101))
    assert r.data["trend"]=="BULLISH"
    assert r.data["reversal_direction"]=="BEARISH"
    assert r.data["phase"].startswith("BEARISH_REVERSAL")


def test_h1_new_bearish_trend_requires_reversal_correction_and_continuation():
    a=seeded()
    a.handle(bar("C1",118,99,99.5))       # breaks bullish control, bearish candidate 120 -> 99
    r=a.handle(bar("C2",108,101,107))     # 9/21 = 42.9%, qualified reversal correction
    assert r.data["trend"]=="BULLISH"
    assert r.data["reversal_correction_qualified"] is True
    r=a.handle(bar("C3",104,97,98))       # continuation below 99 confirms bearish trend
    assert r.data["trend"]=="BEARISH"
    assert r.data["strategic_origin"]["price"]==108
    assert r.data["control_pivot"]["price"]==108
    assert r.data["strategic_endpoint"]["price"]==97
    assert r.reason_codes==["NEW_TREND_CONFIRMED"]
