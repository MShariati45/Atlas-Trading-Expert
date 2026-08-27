from datetime import datetime, timezone
import json

from atlas.execution.account_identity import AccountIdentityDecision
from atlas.execution.account_state import AccountExecutionState
from atlas.execution.controlled_demo_gate import BrokerContract, ControlledDemoExecutionGate, DemoPostFillVerifier, ExecutionLedger
from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.risk_state import StaticAccountRiskStateService, AccountRiskSnapshot
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.services.live_news import LiveNewsGuardService
from atlas.services.news_provider import NewsProviderStatus


class ClearNewsProvider:
    def __init__(self):
        self.status = NewsProviderStatus(True, "TEST", 0, None)
    def events(self, now=None):
        self.status = NewsProviderStatus(True, "TEST", 0, None)
        return []


def _setup(tmp_path, monkeypatch, risk_snapshot=None):
    preflight = tmp_path / "preflight.json"
    preflight.write_text(json.dumps({
        "ready_for_paper_supervision": True,
        "account": {"server": "MetaQuotes-Demo"},
    }))
    enable = tmp_path / "enable.json"
    enable.write_text(json.dumps({"mode": "DEMO_ONLY", "enabled": True}))
    monkeypatch.setenv("ATLAS_DEMO_EXECUTION", "YES")
    approvals = H4HumanApprovalStore(path=tmp_path / "h4.json")
    approvals.approve("EURUSD", "BULLISH", 1.0800, 1.1000, note="owner")
    auth = DemoExecutionAuthorizer(approval_store=approvals, enable_file=enable, preflight_file=preflight)
    baseline = {"symbols": {"EURUSD": {"all": {"median_points": 5.0, "p95_points": 7.0}, "sessions": {}}}}
    spread = AdaptiveSpreadGuard(baseline)
    news = LiveNewsGuardService(ClearNewsProvider())
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    risk = StaticAccountRiskStateService(risk_snapshot or AccountRiskSnapshot(True,0,0,0.0,False))
    gate = ControlledDemoExecutionGate(authorizer=auth, spread_guard=spread, news_service=news,
                                       risk_state_service=risk, ledger=ledger)
    account = AccountConfig("MY-DEMO", True, 0.5, broker="MetaQuotes-Demo")
    ident = AccountIdentityDecision(True, (), 42, "MetaQuotes-Demo", 0)
    state = AccountExecutionState("MY-DEMO").to_observation().authorize_demo(identity=ident, safety_passed=True).enable_execution(explicit_demo_unlock=True)
    signal = ApprovedSignal("sig1", "EURUSD", "LONG", 1.1000, 1.0950, 1.1100)
    contract = BrokerContract(point=0.0001, tick_size=0.0001, tick_value=10.0, volume_min=0.01, volume_max=100.0, volume_step=0.01, stops_level_points=5)
    return gate, account, state, signal, contract, ledger


def test_normal_spread_builds_demo_ticket(tmp_path, monkeypatch):
    gate, account, state, signal, contract, _ = _setup(tmp_path, monkeypatch)
    d = gate.prepare(account, state, signal, account_server="MetaQuotes-Demo", equity=100000, contract=contract,
                     current_spread_points=5.0, now=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc))
    assert d.allowed
    assert d.ticket.execution_mode == "DEMO_ONLY"
    assert d.ticket.risk_cash == 500
    assert d.ticket.volume > 0
    assert d.ticket.spread_status == "NORMAL"


def test_elevated_spread_is_observation_only(tmp_path, monkeypatch):
    gate, account, state, signal, contract, _ = _setup(tmp_path, monkeypatch)
    d = gate.prepare(account, state, signal, account_server="MetaQuotes-Demo", equity=100000, contract=contract,
                     current_spread_points=11.0, now=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc))
    assert not d.allowed
    assert any("SPREAD_STATUS_" in r for r in d.reasons)


def test_live_server_is_hard_rejected(tmp_path, monkeypatch):
    gate, account, state, signal, contract, _ = _setup(tmp_path, monkeypatch)
    d = gate.prepare(account, state, signal, account_server="Broker-Live", equity=100000, contract=contract,
                     current_spread_points=5.0, now=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc))
    assert not d.allowed
    assert "LIVE_REAL_OR_UNVERIFIED_SERVER_FORBIDDEN" in d.reasons


def test_duplicate_signal_is_blocked(tmp_path, monkeypatch):
    gate, account, state, signal, contract, _ = _setup(tmp_path, monkeypatch)
    kwargs = dict(account_server="MetaQuotes-Demo", equity=100000, contract=contract, current_spread_points=5.0,
                  now=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc))
    assert gate.prepare(account, state, signal, **kwargs).allowed
    second = gate.prepare(account, state, signal, **kwargs)
    assert not second.allowed
    assert "DUPLICATE_SIGNAL_ACCOUNT_ALREADY_CLAIMED" in second.reasons


def test_daily_risk_state_blocks_third_trade(tmp_path, monkeypatch):
    snap = AccountRiskSnapshot(True,2,0,1.0,False)
    gate, account, state, signal, contract, _ = _setup(tmp_path, monkeypatch, snap)
    d = gate.prepare(account, state, signal, account_server="MetaQuotes-Demo", equity=100000, contract=contract,
                     current_spread_points=5.0, now=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc))
    assert not d.allowed
    assert "DAILY_TRADE_LIMIT_REACHED" in d.reasons


def test_post_fill_flags_missing_protection(tmp_path, monkeypatch):
    gate, account, state, signal, contract, _ = _setup(tmp_path, monkeypatch)
    d = gate.prepare(account, state, signal, account_server="MetaQuotes-Demo", equity=100000, contract=contract,
                     current_spread_points=5.0, now=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc))
    v = DemoPostFillVerifier().verify(d.ticket, actual_fill_price=1.1001, actual_sl=0.0, actual_tp=1.1100,
                                      fill_volume=d.ticket.volume, contract=contract)
    assert v.status == "CRITICAL_PROTECTION_REVIEW"
    assert "BROKER_SL_DOES_NOT_MATCH_AUTHORIZED_STOP" in v.reasons
