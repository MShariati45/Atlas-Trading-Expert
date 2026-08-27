
from atlas.validation.h4_validator import _pct_retrace

def test_bullish_retrace_math():
    assert round(_pct_retrace(100,120,112.36,"BULLISH"),2)==38.2

def test_bearish_retrace_math():
    assert round(_pct_retrace(120,100,107.64,"BEARISH"),2)==38.2

from atlas.validation.h4_validator import Swing, _run_structure


def test_bearish_transition_can_confirm_bullish_reversal():
    swings = [
        Swing(0,"A",120,"HIGH"), Swing(1,"B",100,"LOW"),
        Swing(2,"C",112,"HIGH"), Swing(3,"D",95,"LOW"),
        Swing(4,"E",114,"HIGH"),  # breaks bearish control 112 -> transition
        Swing(5,"F",104,"LOW"),  # higher low
        Swing(6,"G",116,"HIGH"), # new HH -> bullish confirmed
    ]
    trend, phase, origin, endpoint, control, events = _run_structure(swings)
    assert trend == "BULLISH"
    assert phase == "BULLISH_IMPULSE"
    assert origin.price == 104
    assert control.price == 104
    assert endpoint.price == 116
    assert any(e.event == "NEW_TREND_CONFIRMED" and e.reason == "REVERSAL_HL_THEN_HH_CONFIRMED" for e in events)


def test_bearish_transition_cancels_if_old_low_breaks_first():
    swings = [
        Swing(0,"A",120,"HIGH"), Swing(1,"B",100,"LOW"),
        Swing(2,"C",112,"HIGH"), Swing(3,"D",95,"LOW"),
        Swing(4,"E",114,"HIGH"),  # transition
        Swing(5,"F",94,"LOW"),   # old bearish trend resumes
    ]
    trend, phase, origin, endpoint, control, events = _run_structure(swings)
    assert trend == "BEARISH"
    assert endpoint.price == 94
    assert any(e.event == "REVERSAL_CANDIDATE_FAILED" for e in events)

from atlas.validation.h4_validator import Swing, analyze_latest_h4_trendline


def test_h4_validator_trendline_requires_break_and_confirmation():
    bars=[]
    for i in range(20):
        bars.append({"time":f"2026-01-{i+1:02d}T00:00:00+00:00","open":110.0,"high":111.0,"low":109.0,"close":110.0})
    # Descending resistance from index 2/110 to index 8/104.
    swings=[Swing(2,bars[2]["time"],110.0,"HIGH"), Swing(8,bars[8]["time"],104.0,"HIGH")]
    # line at 12 is 100; first close above, then confirmation above.
    bars[12].update(open=99.5, high=102.0, low=99.0, close=101.0)
    bars[13].update(open=101.0, high=103.0, low=100.5, close=102.0)
    result=analyze_latest_h4_trendline(bars,swings,"BEARISH")
    assert result["status"]=="RETIRED"
    assert result["early_direction"]=="BULLISH"


def test_h4_validator_retired_line_preserves_confirmed_early_direction():
    bars=[]
    for i in range(20):
        bars.append({"time":f"2026-02-{i+1:02d}T00:00:00+00:00","open":110.0,"high":111.0,"low":109.0,"close":110.0})
    swings=[Swing(2,bars[2]["time"],110.0,"HIGH"), Swing(8,bars[8]["time"],104.0,"HIGH")]
    bars[12].update(open=99.5, high=102.0, low=99.0, close=101.0)
    bars[13].update(open=101.0, high=103.0, low=100.5, close=102.0)
    result=analyze_latest_h4_trendline(bars,swings,"BEARISH")
    assert result["status"] == "RETIRED"
    assert result["confirmation_status"] == "EARLY_DIRECTION_CONFIRMED"
    assert result["early_direction"] == "BULLISH"
    assert result["retired_time"] == result["confirmation"]["time"]
