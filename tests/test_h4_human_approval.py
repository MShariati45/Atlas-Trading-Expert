from atlas.services.h4_human_approval import H4HumanApprovalStore

def test_missing_blocks(tmp_path):
    s=H4HumanApprovalStore(tmp_path/'a.json')
    assert s.execution_gate('EURUSD','LONG')[0] is False

def test_directional_approval_and_conflict(tmp_path):
    s=H4HumanApprovalStore(tmp_path/'a.json')
    s.approve('XAUUSD','BULLISH',4310.66,4629.13)
    assert s.execution_gate('XAUUSD','LONG')[0] is True
    assert s.execution_gate('XAUUSD','SHORT')[0] is False

def test_range_blocks(tmp_path):
    s=H4HumanApprovalStore(tmp_path/'a.json')
    s.approve('EURUSD','RANGE')
    ok, reason=s.execution_gate('EURUSD','LONG')
    assert not ok and 'RANGE' in reason

def test_direction_requires_bounds(tmp_path):
    s=H4HumanApprovalStore(tmp_path/'a.json')
    try:
        s.approve('USDJPY','BEARISH')
        assert False
    except ValueError:
        pass
