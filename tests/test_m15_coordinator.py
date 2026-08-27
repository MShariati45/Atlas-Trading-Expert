from atlas.coordination.m15_coordinator import M15Coordinator


def multiple_report():
    return {
        "agent_id": "M15_MULTIPLE_TOP_BOTTOM",
        "status": "EARLY_REVERSAL_CANDIDATE",
        "data": {
            "pattern_type": "DOUBLE_BOTTOM",
            "entry_reference": 1.1052,
            "raw_stop_anchor": 1.1000,
            "applied_buffer": 0.0005,
            "final_stop": 1.0995,
            "last_reason_code": "BULLISH_NECKLINE_BREAK_EARLY_REVERSAL_CANDIDATE",
        },
    }


def impulse_report():
    return {
        "agent_id": "M15_IMPULSE_CORRECTION",
        "status": "VALID_TRIGGER",
        "data": {
            "phase": "VALID_TRIGGER",
            "trend": "BULLISH",
            "trigger_entry_reference": 1.1060,
            "raw_stop_anchor": 1.1025,
            "applied_buffer": 0.0005,
            "final_stop": 1.1020,
            "last_reason_code": "BULLISH_BOS_CONFIRMED_VALID_TRIGGER",
        },
    }


def test_early_pattern_waits_for_structure_if_alone():
    p = M15Coordinator().build("EURUSD", "LONG", [multiple_report()])
    assert p.coordination_state == "WAITING_FOR_CONFIRMATION"
    assert p.primary_trigger["agent"] == "M15_MULTIPLE_TOP_BOTTOM"


def test_later_impulse_confirmation_is_independent_confirmation():
    p = M15Coordinator().build("EURUSD", "LONG", [multiple_report(), impulse_report()])
    assert p.coordination_state == "READY_FOR_SUPERVISOR_REVIEW"
    assert p.confirmations[0]["relationship"] == "INDEPENDENT_CONFIRMATION"


def test_opposite_actionable_direction_is_conflict():
    bad = impulse_report()
    bad["data"] = {**bad["data"], "trend": "BEARISH"}
    p = M15Coordinator().build("EURUSD", "LONG", [bad])
    assert p.coordination_state == "CONFLICT_REVIEW"
    assert p.conflicts


def test_flag_trigger_can_reach_supervisor_review():
    from atlas.coordination.m15_coordinator import M15Coordinator
    c = M15Coordinator()
    report = {
        "agent_id": "M15_FLAG_PENNANT",
        "status": "VALID_TRIGGER",
        "data": {
            "permitted_direction": "LONG",
            "pattern_type": "BULL_FLAG",
            "entry_reference": 1.1037,
            "raw_stop_anchor": 1.1030,
            "applied_buffer": 0.0005,
            "final_stop": 1.1025,
            "last_reason_code": "BULL_FLAG_PENNANT_BREAKOUT_VALID_TRIGGER",
        },
    }
    p = c.build("EURUSD", "LONG", [report])
    assert p.coordination_state == "READY_FOR_SUPERVISOR_REVIEW"

def test_same_event_is_deduplicated_not_counted_as_independent():
    a = impulse_report(); a['data']['event_id']='evt-1'; a['data']['entry_reference']=1.1060
    b = {'agent_id':'M15_HEAD_SHOULDERS','status':'VALID_TRIGGER','data':{'permitted_direction':'LONG','entry_reference':1.1060,'raw_stop_anchor':1.1025,'applied_buffer':0.0005,'final_stop':1.1020,'event_id':'evt-1','last_reason_code':'HNS_VALID'}}
    p=M15Coordinator().build('EURUSD','LONG',[a,b])
    assert p.duplicates and not p.confirmations

def test_different_event_same_direction_is_independent_confirmation():
    a = impulse_report(); a['data']['event_id']='evt-1'; a['data']['entry_reference']=1.1060
    b = {'agent_id':'M15_HEAD_SHOULDERS','status':'VALID_TRIGGER','data':{'permitted_direction':'LONG','entry_reference':1.1075,'raw_stop_anchor':1.1035,'applied_buffer':0.0005,'final_stop':1.1030,'event_id':'evt-2','last_reason_code':'HNS_VALID'}}
    p=M15Coordinator().build('EURUSD','LONG',[a,b])
    assert p.confirmations

def test_valid_trigger_outranks_early_candidate_and_can_reach_supervisor():
    early = multiple_report()
    valid = {
        "agent_id": "M15_HEAD_SHOULDERS",
        "status": "VALID_TRIGGER",
        "data": {
            "permitted_direction": "LONG",
            "entry_reference": 1.1075,
            "raw_stop_anchor": 1.1035,
            "applied_buffer": 0.0005,
            "final_stop": 1.1030,
            "event_id": "hns-2",
            "last_reason_code": "INVERSE_HEAD_SHOULDERS_VALID_TRIGGER",
        },
    }
    early["data"]["event_id"] = "mtb-1"
    p = M15Coordinator().build("EURUSD", "LONG", [early, valid])
    assert p.primary_trigger["agent"] == "M15_HEAD_SHOULDERS"
    assert p.coordination_state == "READY_FOR_SUPERVISOR_REVIEW"
    assert any(c["agent"] == "M15_MULTIPLE_TOP_BOTTOM" for c in p.confirmations)


def test_ineligible_actionable_report_cannot_reach_supervisor():
    p = M15Coordinator().build(
        "EURUSD",
        "LONG",
        [impulse_report()],
        eligible_agents={"M15_FLAG_PENNANT"},
    )
    assert p.primary_trigger is None
    assert p.coordination_state == "COLLECTING_REPORTS"
    assert "NO_ACTIONABLE_M15_TRIGGER" in p.reason_codes


def test_structure_risk_forces_coordinator_sleep():
    p = M15Coordinator().build(
        "EURUSD",
        "LONG",
        [impulse_report()],
        eligible_agents={"M15_IMPULSE_CORRECTION"},
        blocked_reason="M15_BLOCKED_BY_H1_STRUCTURE_RISK",
    )
    assert p.coordination_state == "SLEEPING"
    assert p.primary_trigger is None
    assert p.reason_codes == ["M15_BLOCKED_BY_H1_STRUCTURE_RISK"]

def test_normalized_primary_trigger_contains_auditable_stop_and_event_fields():
    r = impulse_report()
    r['data'].update({'raw_stop_anchor': 1.1025, 'applied_buffer': 0.0005, 'bos_time': '2026-08-19T10:15:00Z'})
    p = M15Coordinator().build('EURUSD', 'LONG', [r])
    t = p.primary_trigger
    assert p.coordination_state == 'READY_FOR_SUPERVISOR_REVIEW'
    assert t['entry_reference'] == 1.1060
    assert t['raw_stop_anchor'] == 1.1025
    assert t['applied_buffer'] == 0.0005
    assert t['final_stop'] == 1.1020
    assert t['trigger_time'] == '2026-08-19T10:15:00Z'
    assert t['event_id'] is not None
    assert t['freshness'] == 'VALID'


def test_actionable_report_missing_structural_stop_contract_is_blocked():
    r = impulse_report()
    r['data'].pop('final_stop')
    p = M15Coordinator().build('EURUSD', 'LONG', [r])
    assert p.primary_trigger is None
    assert p.coordination_state == 'CONFLICT_REVIEW'
    assert 'MISSING_FINAL_STOP' in p.conflicts[0]['contract_errors']

def test_different_trigger_times_same_price_are_independent_not_duplicates():
    a = impulse_report()
    a['data'].update({'bos_time':'2026-08-19T10:15:00Z','trigger_entry_reference':1.1060})
    b = {'agent_id':'M15_HEAD_SHOULDERS','status':'VALID_TRIGGER','data':{
        'permitted_direction':'LONG','entry_reference':1.1060,'raw_stop_anchor':1.1025,
        'applied_buffer':0.0005,'final_stop':1.1020,'breakout_time':'2026-08-19T10:30:00Z',
        'last_reason_code':'INVERSE_HEAD_SHOULDERS_VALID_TRIGGER'}}
    p=M15Coordinator().build('EURUSD','LONG',[a,b])
    assert not p.duplicates
    assert p.confirmations


def test_same_trigger_time_across_specialist_specific_time_fields_is_duplicate():
    a = impulse_report()
    a['data']['bos_time']='2026-08-19T10:15:00Z'
    b = {'agent_id':'M15_TRIANGLE_WEDGE','status':'VALID_TRIGGER','data':{
        'permitted_direction':'LONG','entry_reference':1.1070,'raw_stop_anchor':1.1030,
        'applied_buffer':0.0005,'final_stop':1.1025,'structural_break_time':'2026-08-19T10:15:00Z',
        'last_reason_code':'BULL_TRIANGLE_WEDGE_STRUCTURAL_BREAK_VALID_TRIGGER'}}
    p=M15Coordinator().build('EURUSD','LONG',[a,b])
    assert p.duplicates
    assert not p.confirmations
