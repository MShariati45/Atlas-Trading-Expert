from atlas.agents.m15_multiple_top_bottom import MultipleTopBottomEngine, Pivot


def market(atr=0.0010):
    return {"atr": atr, "spread": 0.00008, "wick_stat": 0.00030, "tick_size": 0.00001, "time": "x"}


def test_double_bottom_only_confirms_after_neckline_close():
    e = MultipleTopBottomEngine()
    s = e.seed(permitted_direction="LONG", prior_trend="BEARISH")
    e.register_pivot(s, Pivot("LOW", 1.1000, "p1", 1), market())
    e.register_pivot(s, Pivot("HIGH", 1.1050, "p2", 4), market())
    e.register_pivot(s, Pivot("LOW", 1.1001, "p3", 8), market())
    assert s.pattern_type == "DOUBLE_BOTTOM"
    assert s.pattern_state == "MATURE"
    assert s.entry_reference is None
    e.update_bar(s, {**market(), "time": "b1", "close": 1.1049})
    assert s.pattern_state == "MATURE"
    e.update_bar(s, {**market(), "time": "b2", "close": 1.1052})
    assert s.pattern_state == "EARLY_REVERSAL_CANDIDATE"
    assert s.notify_impulse_correction is True
    assert s.final_stop < s.raw_stop_anchor


def test_double_top_only_confirms_after_neckline_close():
    e = MultipleTopBottomEngine()
    s = e.seed(permitted_direction="SHORT", prior_trend="BULLISH")
    e.register_pivot(s, Pivot("HIGH", 1.2000, "p1", 1), market())
    e.register_pivot(s, Pivot("LOW", 1.1950, "p2", 4), market())
    e.register_pivot(s, Pivot("HIGH", 1.1999, "p3", 8), market())
    assert s.pattern_type == "DOUBLE_TOP"
    e.update_bar(s, {**market(), "time": "b1", "close": 1.1948})
    assert s.pattern_state == "EARLY_REVERSAL_CANDIDATE"
    assert s.final_stop > s.raw_stop_anchor


def test_triple_bottom_detected_as_multiple_bottom_family():
    e = MultipleTopBottomEngine()
    s = e.seed(permitted_direction="LONG", prior_trend="BEARISH")
    pts = [
        Pivot("LOW", 1.1000, "p1", 1), Pivot("HIGH", 1.1050, "p2", 4),
        Pivot("LOW", 1.1001, "p3", 8), Pivot("HIGH", 1.1054, "p4", 11),
        Pivot("LOW", 1.0999, "p5", 15),
    ]
    for p in pts:
        e.register_pivot(s, p, market())
    assert s.pattern_type == "TRIPLE_BOTTOM"
    assert s.neckline.price == 1.1054


def test_pattern_does_not_force_structure_confirmation():
    e = MultipleTopBottomEngine()
    s = e.seed(permitted_direction="LONG", prior_trend="BEARISH")
    for p in [Pivot("LOW", 1.1000, "p1", 1), Pivot("HIGH", 1.1050, "p2", 4), Pivot("LOW", 1.1001, "p3", 8)]:
        e.register_pivot(s, p, market())
    e.update_bar(s, {**market(), "time": "b", "close": 1.1052})
    assert s.structural_confirmation_status == "PENDING"
    e.apply_structure_confirmation(s, "CONFIRMED", "later")
    assert s.structural_confirmation_status == "CONFIRMED"


def test_wrong_direction_never_confirms_pattern():
    e = MultipleTopBottomEngine()
    # A prior bearish trend with SHORT permission is not eligible for double-bottom reversal.
    s = e.seed(permitted_direction="SHORT", prior_trend="BEARISH")
    for p in [Pivot("LOW", 1.1000, "p1", 1), Pivot("HIGH", 1.1050, "p2", 4), Pivot("LOW", 1.1001, "p3", 8)]:
        e.register_pivot(s, p, market())
    assert s.pattern_type == "NONE"


def test_early_candidate_becomes_stale_if_not_acted_on():
    e = MultipleTopBottomEngine()
    s = e.seed(permitted_direction="LONG", prior_trend="BEARISH")
    for p in [Pivot("LOW", 1.1000, "p1", 1), Pivot("HIGH", 1.1050, "p2", 4), Pivot("LOW", 1.1001, "p3", 8)]:
        e.register_pivot(s, p, market())
    e.update_bar(s, {**market(), "time": "b0", "close": 1.1052})
    for i in range(4):
        e.update_bar(s, {**market(), "time": f"b{i+1}", "close": 1.1060})
    assert s.pattern_state == "STALE"
