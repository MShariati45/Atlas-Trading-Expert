from atlas.research.structure_v2 import analyze_structure, _correction_quality, ResearchPivot, _atr


def bars_from(closes, wick_low=None):
    out=[]
    for i,c in enumerate(closes):
        o=closes[i-1] if i else c
        hi=max(o,c)+0.2
        lo=min(o,c)-0.2
        if wick_low and i in wick_low: lo=wick_low[i]
        out.append({"time":f"2026-01-{1+i//24:02d}T{i%24:02d}:00:00+00:00","open":o,"high":hi,"low":lo,"close":c})
    return out


def test_single_wick_reaction_does_not_become_qualified_correction():
    closes=[100+i*1.0 for i in range(25)] + [124.5,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143]
    b=bars_from(closes,wick_low={25:114.0})
    r=analyze_structure(b,symbol="TEST",timeframe="H4",wing=1)
    if r.current_correction is not None:
        assert not r.current_correction.qualified


def test_wick_penetration_without_body_acceptance_is_rejected():
    b=bars_from([100,102,104,106,108,110,109.8,109.7,110.5,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141], wick_low={6:105.0})
    a=_atr(b)
    q=_correction_quality(b,a,impulse_origin=ResearchPivot(0,b[0]["time"],100,"LOW"),impulse_endpoint=ResearchPivot(5,b[5]["time"],110,"HIGH"),correction_pivot=ResearchPivot(6,b[6]["time"],105,"LOW"),trend="BULLISH")
    assert q.depth > 0.382
    assert not q.structural_acceptance
    assert not q.qualified


def test_research_output_is_timeframe_independent_contract():
    closes=[100,101,102,103,104,105,104,103,102,103,104,105,106,107,108,109,108,107,106,107,108,109,110,111,112,113,112,111,110,111,112,113,114,115,116,117,116,115,116,117,118,119,120,121,122,123,124,125]
    r=analyze_structure(bars_from(closes),symbol="TEST",timeframe="M15",wing=1)
    assert r.timeframe=="M15"
    assert r.dominant_trend in {"BULLISH","BEARISH","UNRESOLVED"}
    assert r.regime in {"IMPULSE","CORRECTION","RANGE","TRANSITION"}
    assert isinstance(r.correction_audit,list)


def test_h4_strategic_correction_waits_for_fresh_extreme_before_origin_reset():
    from atlas.research.structure_v2 import _build_persistent_chain, ResearchPivot, _atr
    # Bullish impulse 100 -> 120, deep developed correction to 112. Price has not yet
    # made a fresh HH, so 100->120 remains the last strategic impulse.
    closes = [100,102,105,108,112,116,120,118,116,114,112,113,114,115,116,117]
    b = bars_from(closes)
    a = _atr(b)
    piv = [
        ResearchPivot(0,b[0]["time"],99.8,"LOW"),
        ResearchPivot(6,b[6]["time"],120.2,"HIGH"),
        ResearchPivot(10,b[10]["time"],111.8,"LOW"),
    ]
    chain, audit = _build_persistent_chain(
        b,a,piv,"BULLISH",promotion_indices={0,10},require_continuation_confirmation=True
    )
    assert chain[-1].index == 0
    assert audit and audit[-1].promoted is False


def test_h4_strategic_correction_promotes_only_after_continuation_breaks_prior_endpoint():
    from atlas.research.structure_v2 import _build_persistent_chain, ResearchPivot, _atr
    closes = [100,102,105,108,112,116,120,118,116,114,112,114,117,121,123]
    b = bars_from(closes)
    a = _atr(b)
    piv = [
        ResearchPivot(0,b[0]["time"],99.8,"LOW"),
        ResearchPivot(6,b[6]["time"],120.2,"HIGH"),
        ResearchPivot(10,b[10]["time"],111.8,"LOW"),
        ResearchPivot(14,b[14]["time"],123.2,"HIGH"),
    ]
    chain, audit = _build_persistent_chain(
        b,a,piv,"BULLISH",promotion_indices={0,10},require_continuation_confirmation=True
    )
    assert chain[-1].index == 10
    assert audit and audit[-1].promoted is True


def test_h4_origin_breach_reseeds_current_cycle_instead_of_freezing_stale_origin():
    from atlas.research.structure_v2 import _build_persistent_chain, ResearchPivot, _atr
    # Old bullish origin 100 is decisively breached by a developed move to 94.
    # The research chain must re-seed rather than evaluate all later action from 100.
    closes = [100,104,108,112,116,120,116,110,104,98,94,96,100,104,108,112]
    b = bars_from(closes)
    a = _atr(b)
    piv = [
        ResearchPivot(0,b[0]["time"],99.8,"LOW"),
        ResearchPivot(5,b[5]["time"],120.2,"HIGH"),
        ResearchPivot(10,b[10]["time"],93.8,"LOW"),
        ResearchPivot(15,b[15]["time"],112.2,"HIGH"),
    ]
    chain, audit = _build_persistent_chain(
        b,a,piv,"BULLISH",promotion_indices={0,10},require_continuation_confirmation=True
    )
    assert chain[-1].index == 10
    assert chain[-1].reason == "CURRENT_CYCLE_RESEEDED_AFTER_ORIGIN_BREACH"
    assert any(x.quality.reason == "IMPULSE_ORIGIN_BREACHED" for x in audit)


def test_h4_retrospective_filter_demotes_correction_that_becomes_minor_after_extension():
    from atlas.research.structure_v2 import _retrospective_h4_chain_filter, CorrectionAudit, CorrectionQuality
    # Bearish: 120 -> 100, correction to 110 looked 50% at the time, but the
    # eventual leg from 110 extends to 70.  The 10-point correction is only 25%
    # of the eventual 40-point leg, so it is internal at the final H4 scale.
    b = bars_from([120,116,112,108,104,100,105,110,104,96,88,80,72,70])
    first = ResearchPivot(0,b[0]["time"],120.2,"HIGH",True,"SEED")
    later = ResearchPivot(7,b[7]["time"],110.2,"HIGH",True,"PROMOTED")
    q = CorrectionQuality(6,7,0.5,0.5,2,2,2.0,False,True,True,"QUALIFIED_STRUCTURAL_CORRECTION")
    a = CorrectionAudit("BEARISH",0,5,7,b[7]["time"],110.2,q,True)
    kept = _retrospective_h4_chain_filter(b,[first,later],[a],"BEARISH")
    assert [p.index for p in kept] == [0]
    assert a.promoted is False
    assert a.quality.reason == "DEMOTED_TO_INTERNAL_AFTER_H4_IMPULSE_EXTENSION"


def test_h4_retrospective_filter_keeps_correction_that_remains_strategic_after_extension():
    from atlas.research.structure_v2 import _retrospective_h4_chain_filter, CorrectionAudit, CorrectionQuality
    # Bearish: prior low ~100, correction to 112, eventual new LL ~86.
    # 12 / 26 remains >38.2%, so the correction remains strategic.
    b = bars_from([120,116,112,108,104,100,106,112,108,102,96,90,86])
    first = ResearchPivot(0,b[0]["time"],120.2,"HIGH",True,"SEED")
    later = ResearchPivot(7,b[7]["time"],112.2,"HIGH",True,"PROMOTED")
    q = CorrectionQuality(6,7,0.6,0.6,2,2,2.0,False,True,True,"QUALIFIED_STRUCTURAL_CORRECTION")
    a = CorrectionAudit("BEARISH",0,5,7,b[7]["time"],112.2,q,True)
    kept = _retrospective_h4_chain_filter(b,[first,later],[a],"BEARISH")
    assert [p.index for p in kept] == [0,7]
    assert a.promoted is True
