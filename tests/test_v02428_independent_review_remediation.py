from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from atlas.execution.account_identity import AccountIdentityDecision
from atlas.execution.account_state import AccountExecutionState
from atlas.execution.controlled_demo_gate import BrokerContract, ControlledDemoExecutionGate, DemoExecutionTicket
from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.demo_transport import DemoExecutionAuditLog, DemoOnlyMT5Transport
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.mt5_bridge import MT5PythonBridge, MT5ConnectionSettings
from atlas.execution.risk_state import StaticAccountRiskStateService, AccountRiskSnapshot
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.services.live_news import LiveNewsGuardService
from atlas.services.news_provider import NewsProviderStatus


class Provider:
    def __init__(self, available=True):
        self.available = available
        self.status = NewsProviderStatus(available, "TEST", 0, None, None if available else "down")
    def events(self, now=None):
        self.status = NewsProviderStatus(self.available, "TEST", 0, None, None if self.available else "down")
        return []


def _gate(tmp_path, monkeypatch, *, provider_available=True, approval_now=None, ledger=None):
    pf = tmp_path / "preflight.json"
    pf.write_text(json.dumps({"ready_for_paper_supervision": True, "account": {"server": "Broker-Demo"}}))
    enable = tmp_path / "enable.json"
    enable.write_text(json.dumps({"mode": "DEMO_ONLY", "enabled": True}))
    monkeypatch.setenv("ATLAS_DEMO_EXECUTION", "YES")
    approvals = H4HumanApprovalStore(tmp_path / "h4.json", max_age_hours=24)
    approvals.approve("EURUSD", "BULLISH", 1.08, 1.10, now=approval_now)
    auth = DemoExecutionAuthorizer(approval_store=approvals, enable_file=enable, preflight_file=pf)
    spread = AdaptiveSpreadGuard({"symbols":{"EURUSD":{"all":{"median_points":5.0,"p95_points":7.0},"sessions":{}}}})
    ledger = ledger or SQLiteExecutionLedger(tmp_path / "exec.sqlite3")
    gate = ControlledDemoExecutionGate(
        authorizer=auth,
        spread_guard=spread,
        news_service=LiveNewsGuardService(Provider(provider_available)),
        risk_state_service=StaticAccountRiskStateService(AccountRiskSnapshot(True,0,0,0.0,False)),
        ledger=ledger,
    )
    account = AccountConfig("A-DEMO", True, 0.5, broker="Broker-Demo")
    identity = AccountIdentityDecision(True, (), 42, "Broker-Demo", 0)
    state = AccountExecutionState(account.account_id).to_observation().authorize_demo(identity=identity, safety_passed=True).enable_execution(explicit_demo_unlock=True)
    signal = ApprovedSignal("S1", "EURUSD", "LONG", 1.10, 1.095, 1.11)
    contract = BrokerContract(.0001,.0001,10,.01,100,.01,5)
    return gate, account, state, signal, contract


def test_fail_closed_news_provider_unavailable(tmp_path, monkeypatch):
    gate, account, state, signal, contract = _gate(tmp_path, monkeypatch, provider_available=False)
    d = gate.prepare(account, state, signal, account_server="Broker-Demo", equity=100000,
                     contract=contract, current_spread_points=5,
                     now=datetime(2026,8,20,15,tzinfo=timezone.utc))
    assert not d.allowed
    assert "NEWS_DATA_UNAVAILABLE" in d.reasons


def test_h4_approval_expires(tmp_path, monkeypatch):
    approved = datetime(2026,8,19,12,tzinfo=timezone.utc)
    gate, account, state, signal, contract = _gate(tmp_path, monkeypatch, approval_now=approved)
    d = gate.prepare(account, state, signal, account_server="Broker-Demo", equity=100000,
                     contract=contract, current_spread_points=5,
                     now=approved + timedelta(hours=25))
    assert not d.allowed
    assert "H4_HUMAN_APPROVAL_STALE" in d.reasons


def test_atomic_claim_two_gate_instances_only_one_wins(tmp_path, monkeypatch):
    path = tmp_path / "exec.sqlite3"
    g1, account, state, signal, contract = _gate(tmp_path, monkeypatch, ledger=SQLiteExecutionLedger(path))
    g2, *_ = _gate(tmp_path, monkeypatch, ledger=SQLiteExecutionLedger(path))
    kwargs = dict(account_server="Broker-Demo", equity=100000, contract=contract,
                  current_spread_points=5, now=datetime(2026,8,20,15,tzinfo=timezone.utc))
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda g: g.prepare(account,state,signal,**kwargs), [g1,g2]))
    assert sum(1 for x in results if x.allowed) == 1
    loser = next(x for x in results if not x.allowed)
    assert "DUPLICATE_SIGNAL_ACCOUNT_ALREADY_CLAIMED" in loser.reasons


def test_sqlite_daily_summary_counts_uncertain_send_as_risk(tmp_path):
    ledger = SQLiteExecutionLedger(tmp_path / "exec.sqlite3")
    t = DemoExecutionTicket("T","S","A","Broker-Demo","EURUSD","LONG",1.1,1.095,1.11,2,.5,500,100000,1,5,5,7,"NORMAL",.1,"PASS","CLEAR","DEMO_ONLY","2026-08-20T12:00:00+00:00")
    ledger.claim(t)
    ledger.mark("A","S","SEND_ATTEMPTED")
    summary = ledger.daily_summary("A","EURUSD",datetime(2026,8,20,tzinfo=timezone.utc),datetime(2026,8,21,tzinfo=timezone.utc))
    assert summary["trades_today"] == 1
    assert summary["symbol_trades_today"] == 1
    assert summary["daily_risk_used_pct"] == pytest.approx(.5)


def test_legacy_management_paths_are_disabled():
    b = MT5PythonBridge(execution_enabled=True)
    a = AccountConfig("A", True, .5, broker="Broker-Demo")
    with pytest.raises(PermissionError, match="LEGACY_TRADE_MANAGEMENT_PATH_DISABLED"):
        b.modify_stop(a, "1", 1.0)
    with pytest.raises(PermissionError, match="LEGACY_TRADE_MANAGEMENT_PATH_DISABLED"):
        b.close_position(a, "1")


class FakeMT5NoPosition:
    ACCOUNT_TRADE_MODE_DEMO=0; ACCOUNT_TRADE_MODE_REAL=2
    ORDER_TYPE_BUY=0; ORDER_TYPE_SELL=1; TRADE_ACTION_DEAL=1; TRADE_RETCODE_DONE=10009
    ORDER_TIME_GTC=0; ORDER_FILLING_IOC=1
    def initialize(self, **kwargs): return True
    def last_error(self): return (0,"OK")
    def account_info(self): return SimpleNamespace(login=42,server="Broker-Demo",trade_mode=0,trade_allowed=True,trade_expert=True)
    def symbol_select(self,*a): return True
    def symbol_info(self,*a): return SimpleNamespace(filling_mode=0)
    def symbol_info_tick(self,*a): return SimpleNamespace(ask=1.1,bid=1.0999)
    def order_check(self,req): return SimpleNamespace(retcode=0,comment="ok")
    def order_send(self,req): return SimpleNamespace(retcode=10009,comment="Done",order=1,deal=2,price=req["price"])
    def positions_get(self,**kwargs): return ()
    def history_deals_get(self,**kwargs): return ()


def test_successful_fill_missing_position_does_not_crash(tmp_path):
    ledger = SQLiteExecutionLedger(tmp_path / "exec.sqlite3")
    ticket = DemoExecutionTicket("T","S","A","Broker-Demo","EURUSD","LONG",1.1,1.095,1.11,2,.5,500,100000,1,5,5,7,"NORMAL",.1,"PASS","CLEAR","DEMO_ONLY","2026-08-20T00:00:00+00:00")
    ledger.claim(ticket)
    bridge = MT5PythonBridge({"A":MT5ConnectionSettings(symbol_map={"EURUSD":"EURUSD"})}, execution_enabled=True)
    bridge._mt5 = FakeMT5NoPosition()
    transport = DemoOnlyMT5Transport(bridge, ledger=ledger, audit=DemoExecutionAuditLog(tmp_path/"audit.jsonl"))
    result = transport.execute(AccountConfig("A",True,.5,broker="Broker-Demo"), ApprovedSignal("S","EURUSD","LONG",1.1,1.095,1.11), ticket,
                               expected_login=42, contract=BrokerContract(.0001,.0001,10,.01,100,.01,5))
    assert result.status == "REVIEW_REQUIRED"
    assert "POST_FILL_POSITION_NOT_FOUND" in result.reasons

class FakeMT5SendUncertain(FakeMT5NoPosition):
    def order_send(self, req):
        raise RuntimeError("transport disconnected after send")


def test_uncertain_send_is_durable_and_requires_reconciliation(tmp_path):
    ledger = SQLiteExecutionLedger(tmp_path / "exec.sqlite3")
    ticket = DemoExecutionTicket("T","S","A","Broker-Demo","EURUSD","LONG",1.1,1.095,1.11,2,.5,500,100000,1,5,5,7,"NORMAL",.1,"PASS","CLEAR","DEMO_ONLY","2026-08-20T00:00:00+00:00")
    ledger.claim(ticket)
    bridge = MT5PythonBridge({"A":MT5ConnectionSettings(symbol_map={"EURUSD":"EURUSD"})}, execution_enabled=True)
    bridge._mt5 = FakeMT5SendUncertain()
    transport = DemoOnlyMT5Transport(bridge, ledger=ledger, audit=DemoExecutionAuditLog(tmp_path/"audit.jsonl"))
    result = transport.execute(AccountConfig("A",True,.5,broker="Broker-Demo"), ApprovedSignal("S","EURUSD","LONG",1.1,1.095,1.11), ticket,
                               expected_login=42, contract=BrokerContract(.0001,.0001,10,.01,100,.01,5))
    assert result.status == "RECONCILIATION_REQUIRED"
    assert ledger.get("A","S")["status"] == "RECONCILIATION_REQUIRED"
