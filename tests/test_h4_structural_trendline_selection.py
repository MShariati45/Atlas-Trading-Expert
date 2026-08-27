from atlas.validation.h4_validator import Swing, _structural_trendline_candidates


def _bars(n=120):
    return [{"time": str(i), "open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0} for i in range(n)]


def test_prefers_long_well_spaced_three_touch_bearish_line():
    bars = _bars(140)
    swings = [
        Swing(5, "5", 1.20, "HIGH"),
        Swing(35, "35", 1.17, "HIGH"),
        Swing(70, "70", 1.135, "HIGH"),
        Swing(82, "82", 1.13, "HIGH"),
        Swing(90, "90", 1.129, "HIGH"),
    ]
    c = _structural_trendline_candidates(bars, swings, "BEARISH")
    assert c
    _, span, _, _, _, pts, _ = c[0]
    assert span >= 60
    assert len(pts) >= 2


def test_neighboring_pivots_do_not_count_as_independent_touches():
    bars = _bars(80)
    swings = [
        Swing(5, "5", 1.20, "HIGH"),
        Swing(7, "7", 1.198, "HIGH"),
        Swing(35, "35", 1.17, "HIGH"),
    ]
    c = _structural_trendline_candidates(bars, swings, "BEARISH")
    assert c
    assert c[0][2] == 2
