from datetime import datetime, timezone
from types import SimpleNamespace

from atlas.execution.controlled_demo_gate import DemoExecutionTicket
from atlas.execution.demo_transport import DemoExecutionAuditLog
from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings, MT5PythonBridge
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.execution.trade_management import (
    DemoOnlyTradeManagementTransport,
    ManagedPosition,
    ManagementAction,
    SupervisedDemoManagementGate,
)


def seed_execution(ledger, *, account_id="A-DEMO", signal_id="S1", position_id="33"):
    t = DemoExecutionTicket(
        "T1", signal_id, account_id, "Broker-Demo", "EURUSD", "LONG",
        1.1000, 1.0950, 1.1100, 2.0, .5, 500, 100000, 1.0,
        5, 5, 7, "NORMAL", .1, "PASS", "CLEAR", "DEMO_ONLY",
        "2026-08-21T12:00:00+00:00",
    )
    ledger.claim(t)
    ledger.mark(account_id, signal_id, "VERIFIED", broker_position_id=position_id)
    return t


def pos(current=1.1070, stop=1.0950, *, position_id="33"):
    return ManagedPosition("A-DEMO", position_id, "EURUSD", "LONG", 1.1000, current, stop, 1.1100, 1.0, "S1", 1.0950)


def test_breakeven_gate_requires_1_4r_and_is_idempotent(tmp_path):
    ledger = SQLiteExecutionLedger(tmp_path / "exec.sqlite3")
    seed_execution(ledger)
    gate = SupervisedDemoManagementGate(ledger)
    account = AccountConfig("A-DEMO", True, .5, broker="Broker-Demo")
    low = gate.prepare(account, pos(current=1.1069), ManagementAction.MOVE_STOP_TO_BREAKEVEN)
    assert not low.allowed and "BREAKEVEN_TRIGGER_NOT_REACHED" in low.reasons
    ok = gate.prepare(account, pos(current=1.1070), ManagementAction.MOVE_STOP_TO_BREAKEVEN)
    assert ok.allowed and ok.ticket.requested_stop == 1.1000
    dup = gate.prepare(account, pos(current=1.1071), ManagementAction.MOVE_STOP_TO_BREAKEVEN)
    assert not dup.allowed and "DUPLICATE_MANAGEMENT_ACTION_ALREADY_CLAIMED" in dup.reasons


def test_close_policies_require_explicit_conditions(tmp_path):
    ledger = SQLiteExecutionLedger(tmp_path / "exec.sqlite3")
    seed_execution(ledger)
    gate = SupervisedDemoManagementGate(ledger)
    account = AccountConfig("A-DEMO", True, .5, broker="Broker-Demo")
    thursday = datetime(2026,8,20,15,tzinfo=timezone.utc)
    assert not gate.prepare(account, pos(), ManagementAction.CLOSE_FRIDAY, now=thursday).allowed
    assert not gate.prepare(account, pos(), ManagementAction.CLOSE_PROTECTIVE_NEWS).allowed
    assert not gate.prepare(account, pos(), ManagementAction.EMERGENCY_OWNER_CLOSE).allowed


class FakeMT5Management:
    ACCOUNT_TRADE_MODE_DEMO=0; ACCOUNT_TRADE_MODE_REAL=2
    ORDER_TYPE_BUY=0; ORDER_TYPE_SELL=1
    TRADE_ACTION_DEAL=1; TRADE_ACTION_SLTP=6
    TRADE_RETCODE_DONE=10009; ORDER_TIME_GTC=0; ORDER_FILLING_IOC=1
    def __init__(self, *, demo=True):
        self.demo=demo; self.sent=[]
        self.position=SimpleNamespace(ticket=33,symbol="EURUSD",magic=260826,volume=1.0,sl=1.095,tp=1.11,price_open=1.1)
    def initialize(self, **kwargs): return True
    def last_error(self): return (0,"OK")
    def account_info(self): return SimpleNamespace(login=42,server="Broker-Demo" if self.demo else "Broker-Live",trade_mode=0 if self.demo else 2,trade_allowed=True,trade_expert=True)
    def symbol_info(self,*a): return SimpleNamespace(filling_mode=0,point=.0001)
    def symbol_info_tick(self,*a): return SimpleNamespace(ask=1.1071,bid=1.1070)
    def order_check(self, req): return SimpleNamespace(retcode=0,comment="ok")
    def order_send(self, req):
        self.sent.append(dict(req))
        if req["action"] == self.TRADE_ACTION_SLTP:
            self.position.sl=float(req["sl"])
        else:
            self.position=None
        return SimpleNamespace(retcode=10009,comment="Done",order=101,deal=202,price=req.get("price",1.1070))
    def positions_get(self, **kwargs):
        if self.position is None: return ()
        if "ticket" in kwargs and int(kwargs["ticket"]) != 33: return ()
        return (self.position,)


def make_transport(tmp_path, fake, action, **prepare_kwargs):
    ledger=SQLiteExecutionLedger(tmp_path/"exec.sqlite3")
    seed_execution(ledger)
    gate=SupervisedDemoManagementGate(ledger)
    account=AccountConfig("A-DEMO",True,.5,broker="Broker-Demo")
    decision=gate.prepare(account,pos(),action,**prepare_kwargs)
    assert decision.allowed
    bridge=MT5PythonBridge({"A-DEMO":MT5ConnectionSettings(login=42,server="Broker-Demo",symbol_map={"EURUSD":"EURUSD"})},execution_enabled=True)
    bridge._mt5=fake
    transport=DemoOnlyTradeManagementTransport(bridge,ledger,audit=DemoExecutionAuditLog(tmp_path/"mgt_audit.jsonl"))
    return transport,account,decision.ticket,ledger


def test_breakeven_transport_rechecks_demo_and_verifies_stop(tmp_path):
    f=FakeMT5Management(demo=True)
    transport,account,ticket,ledger=make_transport(tmp_path,f,ManagementAction.MOVE_STOP_TO_BREAKEVEN)
    r=transport.execute(account,ticket,expected_login=42)
    assert r.status == "VERIFIED"
    assert f.position.sl == 1.1
    assert ledger.get_management_action(ticket.idempotency_key)["status"] == "VERIFIED"


def test_live_account_is_blocked_before_management_send(tmp_path):
    f=FakeMT5Management(demo=False)
    transport,account,ticket,_=make_transport(tmp_path,f,ManagementAction.MOVE_STOP_TO_BREAKEVEN)
    r=transport.execute(account,ticket,expected_login=42)
    assert r.status == "BLOCKED"
    assert f.sent == []


def test_full_close_is_supervised_and_verified(tmp_path):
    f=FakeMT5Management(demo=True)
    friday=datetime(2026,8,21,20,tzinfo=timezone.utc)
    transport,account,ticket,ledger=make_transport(tmp_path,f,ManagementAction.CLOSE_FRIDAY,now=friday)
    r=transport.execute(account,ticket,expected_login=42)
    assert r.status == "VERIFIED"
    assert f.position is None
    assert ledger.get_management_action(ticket.idempotency_key)["status"] == "VERIFIED"


def test_management_position_must_be_owned_by_execution_ledger(tmp_path):
    ledger=SQLiteExecutionLedger(tmp_path/"exec.sqlite3")
    seed_execution(ledger, position_id="33")
    gate=SupervisedDemoManagementGate(ledger)
    account=AccountConfig("A-DEMO",True,.5,broker="Broker-Demo")
    d=gate.prepare(account,pos(position_id="999"),ManagementAction.MOVE_STOP_TO_BREAKEVEN)
    assert not d.allowed and "POSITION_NOT_OWNED_BY_ATLAS_EXECUTION_LEDGER" in d.reasons
