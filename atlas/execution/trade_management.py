from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

from atlas.execution.account_identity import AccountIdentityVerifier
from atlas.execution.demo_transport import DemoExecutionAuditLog
from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5PythonBridge
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.risk.policy import RiskPolicy


class ManagementAction(str, Enum):
    MOVE_STOP_TO_BREAKEVEN = "MOVE_STOP_TO_BREAKEVEN"
    CLOSE_FRIDAY = "CLOSE_FRIDAY"
    CLOSE_PROTECTIVE_NEWS = "CLOSE_PROTECTIVE_NEWS"
    EMERGENCY_OWNER_CLOSE = "EMERGENCY_OWNER_CLOSE"


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    account_id: str
    position_id: str
    symbol: str
    direction: str
    entry_price: float
    current_price: float
    stop: float
    target: float
    volume: float
    signal_id: str
    original_stop: float

    @property
    def current_r(self) -> float:
        risk = abs(float(self.entry_price) - float(self.original_stop))
        if risk <= 0:
            return float("-inf")
        if self.direction.upper() == "LONG":
            return (float(self.current_price) - float(self.entry_price)) / risk
        return (float(self.entry_price) - float(self.current_price)) / risk


@dataclass(frozen=True, slots=True)
class DemoManagementTicket:
    management_id: str
    idempotency_key: str
    account_id: str
    position_id: str
    signal_id: str
    symbol: str
    direction: str
    action: str
    reason: str
    current_r: float
    entry_price: float
    current_price: float
    current_stop: float
    current_target: float
    requested_stop: float | None
    volume: float
    execution_mode: str
    prepared_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ManagementDecision:
    allowed: bool
    reasons: tuple[str, ...]
    ticket: DemoManagementTicket | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "ticket": self.ticket.to_dict() if self.ticket else None,
        }


@dataclass(frozen=True, slots=True)
class ManagementTransportResult:
    status: str
    action: str
    position_id: str
    broker_order_id: str | None
    broker_deal_id: str | None
    reasons: tuple[str, ...]
    completed_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SupervisedDemoManagementGate:
    """Policy gate for changes to an already-open Atlas DEMO position.

    This gate intentionally supports only the frozen v0.24.29 management set:
    breakeven at >= +1.4R, mandatory Friday close, explicitly authorized
    protective/news close, and explicitly authorized Owner emergency close.
    It cannot create a new position, scale in/out, trail stops, or loosen risk.
    """

    def __init__(self, ledger: SQLiteExecutionLedger, *, risk_policy: RiskPolicy | None = None) -> None:
        self.ledger = ledger
        self.risk = risk_policy or RiskPolicy()

    def _execution_owner(self, position: ManagedPosition) -> dict[str, Any] | None:
        row = self.ledger.find_execution_for_position(position.account_id, position.position_id)
        if row is None:
            return None
        if str(row.get("signal_id")) != str(position.signal_id):
            return None
        return row

    @staticmethod
    def _stop_improves_or_equal(position: ManagedPosition, proposed: float) -> bool:
        if position.direction.upper() == "LONG":
            return float(proposed) >= float(position.stop) - 1e-12
        return float(proposed) <= float(position.stop) + 1e-12

    def prepare(
        self,
        account: AccountConfig,
        position: ManagedPosition,
        action: ManagementAction | str,
        *,
        now: datetime | None = None,
        protective_close_authorized: bool = False,
        owner_authorized: bool = False,
    ) -> ManagementDecision:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        action = ManagementAction(str(action)) if not isinstance(action, ManagementAction) else action
        reasons: list[str] = []
        if position.account_id != account.account_id:
            reasons.append("MANAGEMENT_ACCOUNT_POSITION_MISMATCH")
        if self._execution_owner(position) is None:
            reasons.append("POSITION_NOT_OWNED_BY_ATLAS_EXECUTION_LEDGER")

        requested_stop: float | None = None
        reason = action.value
        if action is ManagementAction.MOVE_STOP_TO_BREAKEVEN:
            requested_stop = float(position.entry_price)
            if position.current_r + 1e-9 < float(self.risk.breakeven_trigger_r):
                reasons.append("BREAKEVEN_TRIGGER_NOT_REACHED")
            if not self._stop_improves_or_equal(position, requested_stop):
                reasons.append("BREAKEVEN_WOULD_LOOSEN_EXISTING_STOP")
            # If already at/beyond BE there is nothing to mutate.
            if position.direction.upper() == "LONG" and position.stop >= position.entry_price - 1e-12:
                reasons.append("BREAKEVEN_ALREADY_APPLIED")
            if position.direction.upper() == "SHORT" and position.stop <= position.entry_price + 1e-12:
                reasons.append("BREAKEVEN_ALREADY_APPLIED")
        elif action is ManagementAction.CLOSE_FRIDAY:
            if now.weekday() != 4:
                reasons.append("FRIDAY_CLOSE_ONLY_ALLOWED_ON_FRIDAY")
        elif action is ManagementAction.CLOSE_PROTECTIVE_NEWS:
            if not protective_close_authorized:
                reasons.append("PROTECTIVE_CLOSE_NOT_AUTHORIZED")
        elif action is ManagementAction.EMERGENCY_OWNER_CLOSE:
            if not owner_authorized:
                reasons.append("OWNER_EMERGENCY_CLOSE_NOT_AUTHORIZED")

        if reasons:
            return ManagementDecision(False, tuple(reasons), None)

        # One BE mutation per position. A close is one terminal action per position.
        action_key = "BREAKEVEN" if action is ManagementAction.MOVE_STOP_TO_BREAKEVEN else "CLOSE"
        idempotency_key = f"{position.account_id}:{position.position_id}:{action_key}"
        ticket = DemoManagementTicket(
            management_id=f"MGT-{uuid.uuid4().hex[:16]}",
            idempotency_key=idempotency_key,
            account_id=position.account_id,
            position_id=position.position_id,
            signal_id=position.signal_id,
            symbol=position.symbol,
            direction=position.direction.upper(),
            action=action.value,
            reason=reason,
            current_r=float(position.current_r),
            entry_price=float(position.entry_price),
            current_price=float(position.current_price),
            current_stop=float(position.stop),
            current_target=float(position.target),
            requested_stop=requested_stop,
            volume=float(position.volume),
            execution_mode="DEMO_ONLY",
            prepared_at_utc=now.isoformat(),
        )
        try:
            self.ledger.claim_management_action(ticket)
        except PermissionError:
            return ManagementDecision(False, ("DUPLICATE_MANAGEMENT_ACTION_ALREADY_CLAIMED",), None)
        return ManagementDecision(True, (), ticket)


class DemoOnlyTradeManagementTransport:
    """Only legal MT5 mutation path for existing Atlas DEMO positions.

    Re-verifies authoritative MT5 DEMO identity at mutation time, verifies the
    broker position belongs to the Atlas execution ledger, writes durable
    management states before/after broker mutation, never retries, and verifies
    the resulting broker position state.
    """

    def __init__(
        self,
        bridge: MT5PythonBridge,
        ledger: SQLiteExecutionLedger,
        *,
        audit: DemoExecutionAuditLog | None = None,
    ) -> None:
        self.bridge = bridge
        self.ledger = ledger
        self.audit = audit or DemoExecutionAuditLog("runtime/demo_management_audit.jsonl")
        self.identity_verifier = AccountIdentityVerifier()

    def _identity(self, account: AccountConfig, expected_login: int | None) -> tuple[bool, list[str], dict[str, Any]]:
        mt5 = self.bridge._module()
        info = mt5.account_info()
        if info is None:
            return False, ["MT5_ACCOUNT_INFO_UNAVAILABLE"], {}
        decision = self.identity_verifier.from_mt5(account, info, mt5, expected_login=expected_login)
        return decision.demo_verified, list(decision.reasons), decision.to_dict()

    @staticmethod
    def _position(mt5: Any, position_id: str):
        try:
            rows = mt5.positions_get(ticket=int(position_id)) or ()
        except Exception:
            rows = ()
        return rows[0] if rows else None

    @staticmethod
    def _choose_filling_mode(mt5: Any, info: Any, override: int | None = None) -> int:
        if override is not None:
            return int(override)
        flags = int(getattr(info, "filling_mode", 0) or 0)
        symbol_ioc = int(getattr(mt5, "SYMBOL_FILLING_IOC", 2))
        symbol_fok = int(getattr(mt5, "SYMBOL_FILLING_FOK", 1))
        if flags & symbol_ioc and hasattr(mt5, "ORDER_FILLING_IOC"):
            return int(mt5.ORDER_FILLING_IOC)
        if flags & symbol_fok and hasattr(mt5, "ORDER_FILLING_FOK"):
            return int(mt5.ORDER_FILLING_FOK)
        return int(getattr(mt5, "ORDER_FILLING_IOC", 1))

    def _preflight_position(self, account: AccountConfig, ticket: DemoManagementTicket, expected_login: int | None):
        reasons: list[str] = []
        if ticket.execution_mode != "DEMO_ONLY":
            reasons.append("NON_DEMO_MANAGEMENT_TICKET_FORBIDDEN")
        if ticket.account_id != account.account_id:
            reasons.append("MANAGEMENT_TICKET_ACCOUNT_MISMATCH")
        if not self.bridge.execution_enabled:
            reasons.append("MT5_EXECUTION_DISABLED")
        if reasons:
            return None, None, None, reasons, {}

        self.bridge.connect(account)
        ok, identity_reasons, identity = self._identity(account, expected_login)
        if not ok:
            reasons.extend(identity_reasons)
            return None, None, None, reasons, identity
        mt5 = self.bridge._module()
        owner = self.ledger.find_execution_for_position(account.account_id, ticket.position_id)
        if owner is None or str(owner.get("signal_id")) != str(ticket.signal_id):
            reasons.append("POSITION_NOT_OWNED_BY_ATLAS_EXECUTION_LEDGER")
            return mt5, None, None, reasons, identity
        pos = self._position(mt5, ticket.position_id)
        if pos is None:
            reasons.append("BROKER_POSITION_NOT_FOUND")
            return mt5, None, None, reasons, identity
        broker_symbol = self.bridge.broker_symbol(account, ticket.symbol)
        actual_symbol = str(getattr(pos, "symbol", broker_symbol) or broker_symbol)
        if actual_symbol != broker_symbol:
            reasons.append("BROKER_POSITION_SYMBOL_MISMATCH")
        settings = self.bridge.settings_by_account.get(account.account_id)
        magic = int(settings.atlas_magic if settings else 260826)
        if int(getattr(pos, "magic", magic) or 0) != magic:
            reasons.append("BROKER_POSITION_MAGIC_MISMATCH")
        return mt5, pos, broker_symbol, reasons, identity

    def execute(
        self,
        account: AccountConfig,
        ticket: DemoManagementTicket,
        *,
        expected_login: int | None,
    ) -> ManagementTransportResult:
        now = datetime.now(timezone.utc).isoformat()
        mt5, pos, symbol, reasons, identity = self._preflight_position(account, ticket, expected_login)
        if reasons:
            self.ledger.mark_management_action(ticket.idempotency_key, "BLOCKED_AT_TRANSPORT", reasons=reasons)
            self.audit.append({"event": "MANAGEMENT_BLOCKED", "ticket": ticket.to_dict(), "identity": identity, "reasons": reasons})
            return ManagementTransportResult("BLOCKED", ticket.action, ticket.position_id, None, None, tuple(reasons), now)
        assert mt5 is not None and pos is not None and symbol is not None

        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            reasons = ["BROKER_SYMBOL_OR_TICK_UNAVAILABLE"]
            self.ledger.mark_management_action(ticket.idempotency_key, "FAILED", reasons=reasons)
            return ManagementTransportResult("FAILED", ticket.action, ticket.position_id, None, None, tuple(reasons), now)

        settings = self.bridge.settings_by_account.get(account.account_id)
        deviation = int(settings.max_deviation_points if settings else 20)
        magic = int(settings.atlas_magic if settings else 260826)
        filling_override = settings.filling_mode_override if settings else None

        if ticket.action == ManagementAction.MOVE_STOP_TO_BREAKEVEN.value:
            if ticket.requested_stop is None:
                reasons = ["MANAGEMENT_REQUESTED_STOP_MISSING"]
                self.ledger.mark_management_action(ticket.idempotency_key, "FAILED", reasons=reasons)
                return ManagementTransportResult("FAILED", ticket.action, ticket.position_id, None, None, tuple(reasons), now)
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": int(ticket.position_id),
                "symbol": symbol,
                "sl": float(ticket.requested_stop),
                "tp": float(getattr(pos, "tp", ticket.current_target) or ticket.current_target),
                "magic": magic,
                "comment": f"AtlasBE {ticket.signal_id}"[:31],
            }
        else:
            is_long = ticket.direction.upper() == "LONG"
            close_type = mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY
            close_price = float(tick.bid if is_long else tick.ask)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": int(ticket.position_id),
                "symbol": symbol,
                "volume": float(getattr(pos, "volume", ticket.volume) or ticket.volume),
                "type": close_type,
                "price": close_price,
                "deviation": deviation,
                "magic": magic,
                "comment": f"AtlasClose {ticket.signal_id}"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._choose_filling_mode(mt5, info, filling_override),
            }

        check = mt5.order_check(request)
        check_ok = check is not None and int(getattr(check, "retcode", -1)) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)), 0,
        }
        if not check_ok:
            reason = f"MT5_MANAGEMENT_ORDER_CHECK_FAILED:{getattr(check, 'comment', None)}"
            self.ledger.mark_management_action(ticket.idempotency_key, "ORDER_CHECK_FAILED", reason=reason)
            self.audit.append({"event": "MANAGEMENT_ORDER_CHECK_FAILED", "ticket": ticket.to_dict(), "reason": reason})
            return ManagementTransportResult("FAILED", ticket.action, ticket.position_id, None, None, (reason,), datetime.now(timezone.utc).isoformat())

        self.ledger.mark_management_action(ticket.idempotency_key, "SEND_ATTEMPTED", request_summary={k: v for k, v in request.items() if k != "comment"})
        self.audit.append({"event": "MANAGEMENT_SEND_ATTEMPTED", "ticket": ticket.to_dict()})
        try:
            result = mt5.order_send(request)
        except Exception as exc:
            reason = f"MT5_MANAGEMENT_SEND_UNCERTAIN:{type(exc).__name__}"
            self.ledger.mark_management_action(ticket.idempotency_key, "RECONCILIATION_REQUIRED", reason=reason)
            self.audit.append({"event": "MANAGEMENT_SEND_UNCERTAIN", "ticket": ticket.to_dict(), "reason": reason})
            return ManagementTransportResult("RECONCILIATION_REQUIRED", ticket.action, ticket.position_id, None, None, (reason,), datetime.now(timezone.utc).isoformat())

        if result is None or int(getattr(result, "retcode", -1)) != int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)):
            reason = f"MT5_MANAGEMENT_SEND_FAILED:{getattr(result, 'comment', None)}"
            self.ledger.mark_management_action(ticket.idempotency_key, "SEND_FAILED", reason=reason)
            self.audit.append({"event": "MANAGEMENT_SEND_FAILED", "ticket": ticket.to_dict(), "reason": reason})
            return ManagementTransportResult("FAILED", ticket.action, ticket.position_id, None, None, (reason,), datetime.now(timezone.utc).isoformat())

        order_id = str(getattr(result, "order", "") or "") or None
        deal_id = str(getattr(result, "deal", "") or "") or None
        self.ledger.mark_management_action(ticket.idempotency_key, "SEND_ACKED", broker_order_id=order_id, broker_deal_id=deal_id)

        after = self._position(mt5, ticket.position_id)
        if ticket.action == ManagementAction.MOVE_STOP_TO_BREAKEVEN.value:
            if after is None:
                reasons.append("POSITION_DISAPPEARED_AFTER_STOP_MODIFICATION")
            else:
                point = float(getattr(info, "point", 0.0) or 0.0)
                tolerance = max(point * 2.0, 1e-10)
                actual_sl = float(getattr(after, "sl", 0.0) or 0.0)
                if abs(actual_sl - float(ticket.requested_stop)) > tolerance:
                    reasons.append("BROKER_STOP_DOES_NOT_MATCH_MANAGEMENT_TICKET")
        else:
            if after is not None and float(getattr(after, "volume", 0.0) or 0.0) > 0:
                reasons.append("POSITION_STILL_OPEN_AFTER_FULL_CLOSE")

        status = "VERIFIED" if not reasons else "REVIEW_REQUIRED"
        self.ledger.mark_management_action(ticket.idempotency_key, status, reasons=reasons)
        self.audit.append({
            "event": "MANAGEMENT_COMPLETED",
            "ticket": ticket.to_dict(),
            "identity": identity,
            "order_id": order_id,
            "deal_id": deal_id,
            "status": status,
            "reasons": reasons,
        })
        return ManagementTransportResult(status, ticket.action, ticket.position_id, order_id, deal_id, tuple(reasons), datetime.now(timezone.utc).isoformat())

    def reconcile_account(self, account: AccountConfig, *, expected_login: int | None = None) -> list[dict[str, Any]]:
        """Reconcile uncertain management mutations after restart. Never retries."""
        self.bridge.connect(account)
        ok, reasons, _ = self._identity(account, expected_login)
        if not ok:
            return [{"status": "BLOCKED", "reasons": reasons}]
        mt5 = self.bridge._module()
        out: list[dict[str, Any]] = []
        for row in self.ledger.list_management_by_status(account.account_id, {"SEND_ATTEMPTED", "SEND_ACKED", "RECONCILIATION_REQUIRED"}):
            ticket = row.get("details", {}).get("ticket", {})
            action = str(row.get("action"))
            pos = self._position(mt5, row["position_id"])
            if action == ManagementAction.MOVE_STOP_TO_BREAKEVEN.value:
                requested = ticket.get("requested_stop")
                if pos is not None and requested is not None:
                    actual = float(getattr(pos, "sl", 0.0) or 0.0)
                    if abs(actual - float(requested)) <= 1e-8:
                        self.ledger.mark_management_action(row["idempotency_key"], "VERIFIED", reconciled=True)
                        out.append({"idempotency_key": row["idempotency_key"], "status": "VERIFIED"})
                        continue
            else:
                if pos is None:
                    self.ledger.mark_management_action(row["idempotency_key"], "VERIFIED", reconciled=True)
                    out.append({"idempotency_key": row["idempotency_key"], "status": "VERIFIED"})
                    continue
            self.ledger.mark_management_action(row["idempotency_key"], "RECONCILIATION_REQUIRED", reconciliation_reason="BROKER_STATE_NOT_CONFIRMED")
            out.append({"idempotency_key": row["idempotency_key"], "status": "RECONCILIATION_REQUIRED"})
        return out
