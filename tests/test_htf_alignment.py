from atlas.coordination.htf_alignment import HTFAlignmentService


def test_alignment_compares_independent_reports_downstream():
    s=HTFAlignmentService()
    r=s.evaluate("EURUSD", {"trend":"BULLISH","effective_direction":"BULLISH"}, {"trend":"BULLISH"})
    assert r.aligned is True and r.direction=="BULLISH"


def test_alignment_uses_h4_early_direction_only_downstream():
    s=HTFAlignmentService()
    r=s.evaluate("EURUSD", {"trend":"BEARISH","effective_direction":"BULLISH"}, {"trend":"BULLISH"})
    assert r.aligned is True
    assert r.reason_code=="ALIGNED_WITH_H4_EARLY_DIRECTION"


def test_alignment_mismatch_does_not_modify_agent_reports():
    h4={"trend":"BULLISH","effective_direction":"BULLISH"}
    h1={"trend":"BEARISH"}
    h4_before=dict(h4); h1_before=dict(h1)
    r=HTFAlignmentService().evaluate("EURUSD",h4,h1)
    assert r.aligned is False
    assert h4==h4_before and h1==h1_before


def test_h1_reversal_candidate_blocks_stale_formal_alignment():
    s=HTFAlignmentService()
    r=s.evaluate(
        "EURUSD",
        {"trend":"BULLISH","effective_direction":"BULLISH","phase":"BULLISH_IMPULSE"},
        {"trend":"BULLISH","phase":"BEARISH_REVERSAL_CANDIDATE"},
    )
    assert r.aligned is False
    assert r.state == "WAIT"
    assert r.reason_code == "H1_REVERSAL_STATE_UNRESOLVED"


def test_h1_reversal_correction_qualified_still_waits_until_new_trend_confirmed():
    s=HTFAlignmentService()
    r=s.evaluate(
        "EURUSD",
        {"trend":"BULLISH","effective_direction":"BEARISH","phase":"BULLISH_IMPULSE"},
        {"trend":"BULLISH","phase":"BEARISH_REVERSAL_CORRECTION_QUALIFIED"},
    )
    assert r.aligned is False
    assert r.reason_code == "H1_REVERSAL_STATE_UNRESOLVED"


def test_normal_h1_correction_remains_alignment_eligible_for_fibonacci():
    s=HTFAlignmentService()
    r=s.evaluate(
        "EURUSD",
        {"trend":"BULLISH","effective_direction":"BULLISH","phase":"BULLISH_IMPULSE"},
        {"trend":"BULLISH","phase":"BULLISH_CORRECTION"},
    )
    assert r.aligned is True
    assert r.direction == "BULLISH"


def test_h4_reversal_candidate_without_early_direction_waits():
    s=HTFAlignmentService()
    r=s.evaluate(
        "EURUSD",
        {"trend":"BULLISH","effective_direction":"BULLISH","phase":"BULLISH_REVERSAL_CANDIDATE"},
        {"trend":"BULLISH","phase":"BULLISH_IMPULSE"},
    )
    assert r.aligned is False
    assert r.state == "WAIT"
    assert r.reason_code == "H4_REVERSAL_STATE_UNRESOLVED"


def test_h4_confirmed_early_direction_can_align_during_formal_reversal_transition():
    s=HTFAlignmentService()
    r=s.evaluate(
        "EURUSD",
        {"trend":"BULLISH","effective_direction":"BEARISH","phase":"BULLISH_REVERSAL_CANDIDATE"},
        {"trend":"BEARISH","phase":"BEARISH_IMPULSE"},
    )
    assert r.aligned is True
    assert r.direction == "BEARISH"
    assert r.reason_code == "ALIGNED_WITH_H4_EARLY_DIRECTION"
