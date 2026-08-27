import json
from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.services.h4_human_approval import H4HumanApprovalStore

def setup(tmp_path, monkeypatch):
    approvals=H4HumanApprovalStore(tmp_path/'h4.json'); approvals.approve('EURUSD','BULLISH',1.10,1.12)
    pf=tmp_path/'pf.json'; pf.write_text(json.dumps({'ready_for_paper_supervision':True,'account':{'server':'Broker-Demo'}}))
    en=tmp_path/'enable.json'; en.write_text(json.dumps({'mode':'DEMO_ONLY','enabled':True}))
    monkeypatch.setenv('ATLAS_DEMO_EXECUTION','YES')
    return DemoExecutionAuthorizer(approval_store=approvals,enable_file=en,preflight_file=pf)

def test_demo_allows_only_when_all_gates_pass(tmp_path, monkeypatch):
    a=setup(tmp_path,monkeypatch); acct=AccountConfig('ATLAS_DEMO',True,0.5,broker='Broker Demo')
    s=ApprovedSignal('s','EURUSD','LONG',1.11,1.10,1.13)
    assert a.authorize(acct,s,trades_today=0,symbol_trades_today=0,daily_risk_used_pct=0,open_symbol_position=False).allowed

def test_live_account_is_never_allowed(tmp_path, monkeypatch):
    a=setup(tmp_path,monkeypatch); acct=AccountConfig('LIVE123',True,0.5,broker='Broker Live')
    s=ApprovedSignal('s','EURUSD','LONG',1.11,1.10,1.13)
    d=a.authorize(acct,s,trades_today=0,symbol_trades_today=0,daily_risk_used_pct=0,open_symbol_position=False)
    assert not d.allowed and 'LIVE_OR_UNVERIFIED_ACCOUNT_FORBIDDEN' in d.reasons

def test_limits_fail_closed(tmp_path, monkeypatch):
    a=setup(tmp_path,monkeypatch); acct=AccountConfig('ATLAS_DEMO',True,0.5,broker='Broker Demo')
    s=ApprovedSignal('s','EURUSD','LONG',1.11,1.10,1.13)
    d=a.authorize(acct,s,trades_today=2,symbol_trades_today=1,daily_risk_used_pct=1.0,open_symbol_position=True)
    assert not d.allowed
    assert {'DAILY_TRADE_LIMIT_REACHED','SYMBOL_DAILY_TRADE_LIMIT_REACHED','OPEN_POSITION_ALREADY_EXISTS_FOR_SYMBOL','DAILY_RISK_CAP_EXCEEDED'} <= set(d.reasons)
