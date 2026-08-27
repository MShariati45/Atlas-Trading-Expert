from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
from typing import Any

from atlas.execution.controlled_demo_gate import (
    BrokerContract,
    DemoExecutionTicket,
    DemoPostFillVerifier,
    FillVerification,
)
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.mt5_bridge import MT5PythonBridge
from atlas.execution.account_identity import AccountIdentityVerifier
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger


@dataclass(frozen=True, slots=True)
class DemoTransportResult:
    status: str
    broker_order_id: str | None
    broker_deal_id: str | None
    broker_position_id: str | None
    requested_price: float
    fill_price: float | None
    verification: FillVerification | None
    reasons: tuple[str, ...]
    completed_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.verification is not None:
            d["verification"] = self.verification.to_dict()
        return d


class DemoExecutionAuditLog:
    """Durable hash-chained JSONL audit with explicit secret redaction."""

    _SECRET_KEYS = {"password", "token", "secret", "api_key", "authorization"}

    def __init__(self, path: str | Path = "runtime/demo_execution_audit.jsonl") -> None:
        self.path = Path(path)

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[REDACTED]" if k.lower() in cls._SECRET_KEYS else cls._redact(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._redact(v) for v in value]
        return value

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        try:
            last = self.path.read_text(encoding="utf-8").strip().splitlines()[-1]
            return str(json.loads(last).get("record_hash", "GENESIS"))
        except Exception:
            return "GENESIS"

    def append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = self._redact(dict(event))
        record.setdefault("logged_at_utc", datetime.now(timezone.utc).isoformat())
        record["prev_hash"] = self._last_hash()
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
        record["record_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


class DemoOnlyMT5Transport:
    """Single-shot DEMO-only transport from an authorized ticket to MT5.

    Safety properties:
    - refuses to operate unless bridge execution is explicitly enabled;
    - positively checks MT5 ACCOUNT_TRADE_MODE_DEMO (not merely server naming);
    - optionally enforces the exact expected login;
    - checks broker symbol/trade contract and order_check before order_send;
    - never automatically retries a rejected/failed order;
    - verifies fill price, volume, SL and TP after execution;
    - writes a local audit trail and execution-ledger state;
    - has no AI/API calls.
    """

    def __init__(
        self,
        bridge: MT5PythonBridge,
        *,
        ledger: Any | None = None,
        verifier: DemoPostFillVerifier | None = None,
        audit: DemoExecutionAuditLog | None = None,
    ) -> None:
        self.bridge = bridge
        self.ledger = ledger or SQLiteExecutionLedger()
        self.verifier = verifier or DemoPostFillVerifier()
        self.identity_verifier = AccountIdentityVerifier()
        self.audit = audit or DemoExecutionAuditLog()

    @staticmethod
    def _broker_symbol(bridge: MT5PythonBridge, account_id: str, canonical: str) -> str:
        settings = bridge.settings_by_account.get(account_id)
        mapping = settings.symbol_map if settings and settings.symbol_map else {}
        return str(mapping.get(canonical, canonical))

    def _positive_demo_identity(self, account: AccountConfig, expected_login: int | None) -> tuple[bool, list[str], dict[str, Any]]:
        mt5 = self.bridge._module()
        info = mt5.account_info()
        if info is None:
            return False, ["MT5_ACCOUNT_INFO_UNAVAILABLE"], {}
        decision = self.identity_verifier.from_mt5(account, info, mt5, expected_login=expected_login)
        return decision.demo_verified, list(decision.reasons), decision.to_dict()

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
        # Conservative fallback for older/fake MT5 bindings; order_check is still mandatory.
        return int(getattr(mt5, "ORDER_FILLING_IOC", 1))

    @staticmethod
    def _find_position(mt5: Any, *, symbol: str, order_id: str | None, deal_id: str | None, magic: int, signal_id: str):
        # Prefer exact broker identifiers before any symbol/time fallback.
        if order_id and str(order_id).isdigit():
            try:
                rows = mt5.positions_get(ticket=int(order_id)) or ()
                if rows:
                    return rows[0]
            except Exception:
                pass
        if deal_id and str(deal_id).isdigit() and hasattr(mt5, "history_deals_get"):
            try:
                deals = mt5.history_deals_get(ticket=int(deal_id)) or ()
                for deal in deals:
                    position_id = int(getattr(deal, "position_id", 0) or 0)
                    if position_id:
                        rows = mt5.positions_get(ticket=position_id) or ()
                        if rows:
                            return rows[0]
            except Exception:
                pass
        positions = mt5.positions_get(symbol=symbol) or ()
        candidates = [p for p in positions if int(getattr(p, "magic", 0) or 0) == int(magic)]
        exact_comment = [p for p in candidates if signal_id and signal_id in str(getattr(p, "comment", "") or "")]
        if exact_comment:
            candidates = exact_comment
        if candidates:
            return max(candidates, key=lambda p: int(getattr(p, "time_msc", 0) or getattr(p, "time", 0) or 0))
        return None

    def reconcile_account(self, account: AccountConfig, *, expected_login: int | None = None) -> list[dict[str, Any]]:
        """Reconcile uncertain broker sends after restart/crash. Never resends orders."""
        self.bridge.connect(account)
        ok, identity_reasons, _ = self._positive_demo_identity(account, expected_login)
        if not ok:
            return [{"status": "BLOCKED", "reasons": identity_reasons}]
        mt5 = self.bridge._module()
        settings = self.bridge.settings_by_account.get(account.account_id)
        magic = int(settings.atlas_magic if settings else 260826)
        out: list[dict[str, Any]] = []
        for row in self.ledger.list_by_status(account.account_id, {"SEND_ATTEMPTED", "SEND_ACKED", "RECONCILIATION_REQUIRED"}):
            details = row.get("details", {})
            ticket_data = details.get("ticket", {})
            symbol = self._broker_symbol(self.bridge, account.account_id, row.get("symbol") or ticket_data.get("symbol", ""))
            pos = self._find_position(
                mt5, symbol=symbol, order_id=details.get("broker_order_id"),
                deal_id=details.get("broker_deal_id"), magic=magic, signal_id=row["signal_id"]
            )
            if pos is None:
                self.ledger.mark(account.account_id, row["signal_id"], "RECONCILIATION_REQUIRED",
                                 reconciliation_reason="NO_MATCHING_POSITION_FOUND")
                out.append({"signal_id": row["signal_id"], "status": "RECONCILIATION_REQUIRED"})
                continue
            position_id = str(getattr(pos, "ticket", "") or "") or None
            self.ledger.mark(account.account_id, row["signal_id"], "SEND_ACKED",
                             broker_position_id=position_id, reconciled=True)
            self.audit.append({"event": "RECONCILED_POSITION", "account_id": account.account_id,
                               "signal_id": row["signal_id"], "position_id": position_id})
            out.append({"signal_id": row["signal_id"], "status": "SEND_ACKED", "position_id": position_id})
        return out

    def execute(
        self,
        account: AccountConfig,
        signal: ApprovedSignal,
        ticket: DemoExecutionTicket,
        *,
        expected_login: int | None,
        contract: BrokerContract,
    ) -> DemoTransportResult:
        now = datetime.now(timezone.utc).isoformat()
        reasons: list[str] = []
        if ticket.execution_mode != "DEMO_ONLY":
            reasons.append("NON_DEMO_TICKET_FORBIDDEN")
        if ticket.account_id != account.account_id or ticket.signal_id != signal.signal_id:
            reasons.append("TICKET_ACCOUNT_OR_SIGNAL_MISMATCH")
        if not self.bridge.execution_enabled:
            reasons.append("MT5_EXECUTION_DISABLED")
        if reasons:
            return DemoTransportResult("BLOCKED", None, None, None, ticket.requested_entry, None, None, tuple(reasons), now)

        self.bridge.connect(account)
        ok, identity_reasons, identity = self._positive_demo_identity(account, expected_login)
        if not ok:
            self.ledger.mark(account.account_id, signal.signal_id, "BLOCKED_AT_TRANSPORT", reasons=identity_reasons)
            self.audit.append({"event": "TRANSPORT_BLOCKED", "ticket": ticket.to_dict(), "identity": identity, "reasons": identity_reasons})
            return DemoTransportResult("BLOCKED", None, None, None, ticket.requested_entry, None, None, tuple(identity_reasons), now)

        mt5 = self.bridge._module()
        symbol = self._broker_symbol(self.bridge, account.account_id, signal.symbol)
        if not mt5.symbol_select(symbol, True):
            reasons.append("BROKER_SYMBOL_SELECT_FAILED")
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None:
            reasons.append("BROKER_SYMBOL_INFO_UNAVAILABLE")
        if tick is None:
            reasons.append("BROKER_TICK_UNAVAILABLE")
        if reasons:
            self.ledger.mark(account.account_id, signal.signal_id, "TRANSPORT_FAILED", reasons=reasons)
            self.audit.append({"event": "TRANSPORT_FAILED", "ticket": ticket.to_dict(), "reasons": reasons})
            return DemoTransportResult("FAILED", None, None, None, ticket.requested_entry, None, None, tuple(reasons), datetime.now(timezone.utc).isoformat())

        is_long = signal.direction.upper() == "LONG"
        order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if is_long else tick.bid)
        settings = self.bridge.settings_by_account.get(account.account_id)
        deviation = int(settings.max_deviation_points if settings else 20)
        magic = int(settings.atlas_magic if settings else 260826)
        filling_override = settings.filling_mode_override if settings else None
        filling_mode = self._choose_filling_mode(mt5, info, filling_override)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(ticket.volume),
            "type": order_type,
            "price": price,
            "sl": float(ticket.stop),
            "tp": float(ticket.target),
            "deviation": deviation,
            "magic": magic,
            "comment": f"AtlasDemo {signal.signal_id}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        check = mt5.order_check(request)
        check_ok = check is not None and int(getattr(check, "retcode", -1)) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            0,  # some MT5 builds return zero for successful order_check
        }
        if not check_ok:
            reason = f"MT5_ORDER_CHECK_FAILED:{getattr(check, 'comment', None)}"
            self.ledger.mark(account.account_id, signal.signal_id, "ORDER_CHECK_FAILED", reason=reason)
            self.audit.append({"event": "ORDER_CHECK_FAILED", "ticket": ticket.to_dict(), "request": request, "reason": reason})
            return DemoTransportResult("FAILED", None, None, None, ticket.requested_entry, None, None, (reason,), datetime.now(timezone.utc).isoformat())

        self.ledger.mark(account.account_id, signal.signal_id, "SEND_ATTEMPTED", request_summary={
            "symbol": symbol, "volume": float(ticket.volume), "type": int(order_type),
            "price": price, "sl": float(ticket.stop), "tp": float(ticket.target),
        })
        self.audit.append({"event": "SEND_ATTEMPTED", "ticket": ticket.to_dict(), "broker_symbol": symbol})
        try:
            result = mt5.order_send(request)
        except Exception as exc:
            reason = f"MT5_ORDER_SEND_UNCERTAIN:{type(exc).__name__}"
            self.ledger.mark(account.account_id, signal.signal_id, "RECONCILIATION_REQUIRED", reason=reason)
            self.audit.append({"event": "SEND_UNCERTAIN", "ticket": ticket.to_dict(), "reason": reason})
            return DemoTransportResult("RECONCILIATION_REQUIRED", None, None, None, ticket.requested_entry, None, None, (reason,), datetime.now(timezone.utc).isoformat())
        if result is None or int(getattr(result, "retcode", -1)) != int(mt5.TRADE_RETCODE_DONE):
            reason = f"MT5_ORDER_SEND_FAILED:{getattr(result, 'comment', None)}"
            self.ledger.mark(account.account_id, signal.signal_id, "SEND_FAILED", reason=reason)
            self.audit.append({"event": "SEND_FAILED", "ticket": ticket.to_dict(), "request": request, "reason": reason})
            return DemoTransportResult("FAILED", None, None, None, ticket.requested_entry, None, None, (reason,), datetime.now(timezone.utc).isoformat())

        order_id = str(getattr(result, "order", "") or "") or None
        deal_id = str(getattr(result, "deal", "") or "") or None
        fill_price = float(getattr(result, "price", 0.0) or price)
        self.ledger.mark(account.account_id, signal.signal_id, "SEND_ACKED",
                         broker_order_id=order_id, broker_deal_id=deal_id, fill_price=fill_price)
        self.audit.append({"event": "SEND_ACKED", "ticket_id": ticket.ticket_id,
                           "account_id": account.account_id, "signal_id": signal.signal_id,
                           "order_id": order_id, "deal_id": deal_id, "fill_price": fill_price})
        position_id: str | None = None
        actual_sl, actual_tp, actual_volume = ticket.stop, ticket.target, ticket.volume

        pos = self._find_position(
            mt5, symbol=symbol, order_id=order_id, deal_id=deal_id, magic=magic, signal_id=signal.signal_id
        )
        if pos is not None:
            position_id = str(getattr(pos, "ticket", "") or "") or None
            actual_sl = float(getattr(pos, "sl", actual_sl) or 0.0)
            actual_tp = float(getattr(pos, "tp", actual_tp) or 0.0)
            actual_volume = float(getattr(pos, "volume", actual_volume) or 0.0)
            fill_price = float(getattr(pos, "price_open", fill_price) or fill_price)
        else:
            reasons.append("POST_FILL_POSITION_NOT_FOUND")

        verification = self.verifier.verify(
            ticket,
            actual_fill_price=fill_price,
            actual_sl=actual_sl,
            actual_tp=actual_tp,
            fill_volume=actual_volume,
            contract=contract,
        )
        if reasons:
            verification = FillVerification(
                status="REVIEW_REQUIRED" if verification.status == "PASS" else verification.status,
                reasons=tuple(list(verification.reasons) + reasons),
                slippage_points=verification.slippage_points,
                effective_risk_cash=verification.effective_risk_cash,
                effective_risk_pct=verification.effective_risk_pct,
                fill_volume=verification.fill_volume,
                verified_at_utc=verification.verified_at_utc,
            )

        status = "VERIFIED" if verification.status == "PASS" else verification.status
        self.ledger.mark(
            account.account_id,
            signal.signal_id,
            status,
            broker_order_id=order_id,
            broker_deal_id=deal_id,
            broker_position_id=position_id,
            fill_price=fill_price,
            verification=verification.to_dict(),
        )
        self.audit.append({
            "event": "DEMO_ORDER_COMPLETED",
            "ticket": ticket.to_dict(),
            "identity": identity,
            "broker_symbol": symbol,
            "order_id": order_id,
            "deal_id": deal_id,
            "position_id": position_id,
            "fill_price": fill_price,
            "verification": verification.to_dict(),
        })
        return DemoTransportResult(
            status=status,
            broker_order_id=order_id,
            broker_deal_id=deal_id,
            broker_position_id=position_id,
            requested_price=ticket.requested_entry,
            fill_price=fill_price,
            verification=verification,
            reasons=verification.reasons,
            completed_at_utc=datetime.now(timezone.utc).isoformat(),
        )
