from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from atlas.execution.account_identity import AccountIdentityVerifier
from atlas.execution.account_state import AccountExecutionState
from atlas.execution.broker_contract import MT5BrokerContractService
from atlas.execution.controlled_demo_gate import ControlledDemoExecutionGate, DemoGateDecision
from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.demo_transport import DemoOnlyMT5Transport, DemoTransportResult
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.mt5_bridge import MT5PythonBridge
from atlas.execution.risk_state import MT5AccountRiskStateService
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.live_news import LiveNewsGuardService


class DemoExecutionRuntime:
    """Canonical integration seam for Atlas DEMO execution.

    One runtime owns one shared SQLite ledger and wires authoritative MT5 risk
    state, fail-closed live news, the controlled gate, and the DEMO-only
    transport. Callers do not supply daily counters or open-position booleans.
    """

    def __init__(
        self,
        *,
        bridge: MT5PythonBridge,
        authorizer: DemoExecutionAuthorizer,
        spread_guard: AdaptiveSpreadGuard,
        news_service: LiveNewsGuardService,
        ledger_path: str | Path = "runtime/demo_execution.sqlite3",
    ) -> None:
        self.bridge = bridge
        self.ledger = SQLiteExecutionLedger(ledger_path)
        self.risk_state = MT5AccountRiskStateService(self.ledger, bridge)
        self.contracts = MT5BrokerContractService(bridge)
        self.identity = AccountIdentityVerifier()
        self.gate = ControlledDemoExecutionGate(
            authorizer=authorizer,
            spread_guard=spread_guard,
            news_service=news_service,
            risk_state_service=self.risk_state,
            ledger=self.ledger,
        )
        self.transport = DemoOnlyMT5Transport(bridge, ledger=self.ledger)

    def authorize_account(self, account: AccountConfig, *, safety_passed: bool, explicit_demo_unlock: bool) -> AccountExecutionState:
        self.bridge.connect(account)
        mt5 = self.bridge._module()
        info = mt5.account_info()
        if info is None:
            raise PermissionError("MT5_ACCOUNT_INFO_UNAVAILABLE")
        settings = self.bridge.settings_by_account.get(account.account_id)
        expected_login = settings.login if settings else None
        identity = self.identity.from_mt5(account, info, mt5, expected_login=expected_login)
        return (
            AccountExecutionState(account.account_id)
            .to_observation()
            .authorize_demo(identity=identity, safety_passed=safety_passed)
            .enable_execution(explicit_demo_unlock=explicit_demo_unlock)
        )

    def prepare(self, account: AccountConfig, account_state: AccountExecutionState, signal: ApprovedSignal,
                *, now: datetime | None = None) -> DemoGateDecision:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.bridge.connect(account)
        mt5 = self.bridge._module()
        acct = mt5.account_info()
        if acct is None:
            raise RuntimeError("MT5_ACCOUNT_INFO_UNAVAILABLE")
        broker_symbol = self.bridge.broker_symbol(account, signal.symbol)
        if not mt5.symbol_select(broker_symbol, True):
            raise RuntimeError("BROKER_SYMBOL_SELECT_FAILED")
        info = mt5.symbol_info(broker_symbol)
        tick = mt5.symbol_info_tick(broker_symbol)
        if info is None or tick is None:
            raise RuntimeError("BROKER_SYMBOL_OR_TICK_UNAVAILABLE")
        point = float(getattr(info, "point", 0.0) or 0.0)
        if point <= 0:
            raise RuntimeError("BROKER_POINT_INVALID")
        current_spread_points = abs(float(tick.ask) - float(tick.bid)) / point
        contract = self.contracts.build(account, signal.symbol, signal.direction, signal.entry, signal.stop)
        return self.gate.prepare(
            account, account_state, signal,
            account_server=str(getattr(acct, "server", "") or ""),
            equity=float(getattr(acct, "equity", 0.0) or 0.0),
            contract=contract,
            current_spread_points=current_spread_points,
            now=now,
        )

    def execute(self, account: AccountConfig, account_state: AccountExecutionState, signal: ApprovedSignal,
                decision: DemoGateDecision) -> DemoTransportResult:
        if not decision.allowed or decision.ticket is None:
            raise PermissionError("DEMO_GATE_DECISION_NOT_ALLOWED")
        contract = self.contracts.build(account, signal.symbol, signal.direction, signal.entry, signal.stop)
        return self.transport.execute(
            account, signal, decision.ticket,
            expected_login=account_state.verified_login,
            contract=contract,
        )
