from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from typing import Any

from atlas.execution.account_state import AccountExecutionState, ExecutionConnectionState
from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.risk.policy import RiskPolicy
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.live_news import LiveNewsGuardService
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.execution.risk_state import AccountRiskStateService


@dataclass(frozen=True, slots=True)
class BrokerContract:
    point: float
    tick_size: float
    tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int = 0
    loss_per_lot_at_stop: float | None = None


@dataclass(frozen=True, slots=True)
class DemoExecutionTicket:
    ticket_id: str
    signal_id: str
    account_id: str
    account_server: str
    symbol: str
    direction: str
    requested_entry: float
    stop: float
    target: float
    gross_rr: float
    risk_pct: float
    risk_cash: float
    equity: float
    volume: float
    current_spread_points: float
    normal_spread_median_points: float
    normal_spread_p95_points: float
    spread_status: str
    spread_to_stop_ratio: float | None
    h4_gate: str
    news_gate: str
    execution_mode: str
    prepared_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DemoGateDecision:
    allowed: bool
    reasons: tuple[str, ...]
    ticket: DemoExecutionTicket | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "ticket": self.ticket.to_dict() if self.ticket else None,
        }


@dataclass(frozen=True, slots=True)
class FillVerification:
    status: str
    reasons: tuple[str, ...]
    slippage_points: float
    effective_risk_cash: float
    effective_risk_pct: float
    fill_volume: float
    verified_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ExecutionLedger = SQLiteExecutionLedger


class ControlledDemoExecutionGate:
    """Final deterministic gate before a DEMO-only order can be transmitted.

    For the initial forward-demo phase, ELEVATED spread is observation-only and
    cannot execute. Only NORMAL spread passes. LIVE/REAL account servers are
    categorically rejected. The gate performs no AI/API calls.
    """

    def __init__(
        self,
        *,
        authorizer: DemoExecutionAuthorizer,
        spread_guard: AdaptiveSpreadGuard,
        news_service: LiveNewsGuardService,
        risk_state_service: AccountRiskStateService,
        ledger: SQLiteExecutionLedger | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.authorizer = authorizer
        self.spread_guard = spread_guard
        self.news_service = news_service
        self.ledger = ledger or SQLiteExecutionLedger()
        self.risk_state_service = risk_state_service
        self.risk = risk_policy or RiskPolicy()

    @staticmethod
    def _is_demo_server(server: str) -> bool:
        value = str(server or "").upper()
        return "DEMO" in value and "LIVE" not in value and "REAL" not in value

    @staticmethod
    def _gross_rr(signal: ApprovedSignal) -> float:
        risk = abs(float(signal.entry) - float(signal.stop))
        reward = abs(float(signal.target) - float(signal.entry))
        return reward / risk if risk > 0 else 0.0

    @staticmethod
    def _normalize_volume(raw: float, contract: BrokerContract) -> float:
        if raw <= 0 or contract.volume_step <= 0:
            return 0.0
        steps = math.floor((raw + 1e-12) / contract.volume_step)
        volume = steps * contract.volume_step
        # Round decimal noise according to step precision.
        step_s = f"{contract.volume_step:.12f}".rstrip("0")
        decimals = len(step_s.split(".")[1]) if "." in step_s else 0
        return round(min(volume, contract.volume_max), decimals)

    @staticmethod
    def _volume_for_risk(signal: ApprovedSignal, equity: float, risk_pct: float, contract: BrokerContract) -> tuple[float, float]:
        risk_cash = float(equity) * float(risk_pct) / 100.0
        stop_distance = abs(float(signal.entry) - float(signal.stop))
        if min(risk_cash, stop_distance) <= 0:
            return risk_cash, 0.0
        if contract.loss_per_lot_at_stop is not None and contract.loss_per_lot_at_stop > 0:
            cash_loss_per_lot = float(contract.loss_per_lot_at_stop)
        else:
            if min(contract.tick_size, contract.tick_value) <= 0:
                return risk_cash, 0.0
            cash_loss_per_lot = (stop_distance / contract.tick_size) * contract.tick_value
        raw = risk_cash / cash_loss_per_lot
        return risk_cash, ControlledDemoExecutionGate._normalize_volume(raw, contract)

    def prepare(
        self,
        account: AccountConfig,
        account_state: AccountExecutionState,
        signal: ApprovedSignal,
        *,
        account_server: str,
        equity: float,
        contract: BrokerContract,
        current_spread_points: float,
        now: datetime | None = None,
    ) -> DemoGateDecision:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        reasons: list[str] = []

        if account_state.account_id != account.account_id:
            reasons.append("ACCOUNT_STATE_ID_MISMATCH")
        if account_state.state is not ExecutionConnectionState.EXECUTION_ENABLED:
            reasons.append("ACCOUNT_EXECUTION_STATE_NOT_ENABLED")
        if not account_state.demo_verified or not account_state.safety_passed:
            reasons.append("ACCOUNT_DEMO_SAFETY_STATE_INVALID")
        if not self._is_demo_server(account_server):
            reasons.append("LIVE_REAL_OR_UNVERIFIED_SERVER_FORBIDDEN")

        # Friday/weekend restrictions are independent of signal logic.
        if now.weekday() == 4 and not self.risk.allow_new_trades_friday:
            reasons.append("FRIDAY_NEW_ENTRIES_FORBIDDEN")
        if now.weekday() >= 5:
            reasons.append("WEEKEND_NEW_ENTRIES_FORBIDDEN")

        risk_state = self.risk_state_service.snapshot(account, signal.symbol, now)
        if not risk_state.available:
            reasons.extend(risk_state.reasons or ("ACCOUNT_RISK_STATE_UNAVAILABLE",))

        auth = self.authorizer.authorize(
            account,
            signal,
            trades_today=risk_state.trades_today,
            symbol_trades_today=risk_state.symbol_trades_today,
            daily_risk_used_pct=risk_state.daily_risk_used_pct,
            open_symbol_position=risk_state.open_symbol_position,
            now=now,
        )
        if not auth.allowed:
            reasons.extend(auth.reasons)

        h4_gate = "PASS" if not any("H4" in r or "APPROVAL" in r for r in auth.reasons) else "BLOCK"

        live_news = self.news_service.assess(signal.symbol, now)
        if live_news.gate is not True:
            reasons.extend(live_news.reason_codes or ["NEWS_DATA_UNAVAILABLE"])
        news_gate = "CLEAR" if live_news.gate is True else "BLOCK"

        stop_distance_points = None
        if contract.point > 0:
            stop_distance_points = abs(signal.entry - signal.stop) / contract.point
        spread = self.spread_guard.assess(
            signal.symbol,
            current_spread_points,
            now=now,
            stop_distance_points=stop_distance_points,
        )
        # Initial demo policy: only NORMAL is executable; ELEVATED is shadow-only.
        if spread.status != "NORMAL" or spread.allowed is not True:
            reasons.append(f"SPREAD_STATUS_{spread.status}_NOT_EXECUTABLE")
        reasons.extend(r for r in spread.reasons if r not in reasons)

        rr = self._gross_rr(signal)
        if rr + 1e-9 < self.risk.default_target_r:
            reasons.append("TARGET_BELOW_2R_BASELINE")

        if equity <= 0:
            reasons.append("ACCOUNT_EQUITY_INVALID")
        risk_cash, volume = self._volume_for_risk(signal, equity, account.risk_pct, contract)
        if volume < contract.volume_min - 1e-12:
            reasons.append("CALCULATED_VOLUME_BELOW_BROKER_MINIMUM")
        if volume > contract.volume_max + 1e-12:
            reasons.append("CALCULATED_VOLUME_ABOVE_BROKER_MAXIMUM")

        if contract.point > 0 and contract.stops_level_points > 0:
            stop_points = abs(signal.entry - signal.stop) / contract.point
            target_points = abs(signal.target - signal.entry) / contract.point
            if stop_points < contract.stops_level_points:
                reasons.append("STOP_INSIDE_BROKER_MINIMUM_DISTANCE")
            if target_points < contract.stops_level_points:
                reasons.append("TARGET_INSIDE_BROKER_MINIMUM_DISTANCE")

        if reasons:
            return DemoGateDecision(False, tuple(dict.fromkeys(reasons)), None)

        ticket = DemoExecutionTicket(
            ticket_id=f"DEMO::{account.account_id}::{signal.signal_id}",
            signal_id=signal.signal_id,
            account_id=account.account_id,
            account_server=account_server,
            symbol=signal.symbol,
            direction=signal.direction.upper(),
            requested_entry=float(signal.entry),
            stop=float(signal.stop),
            target=float(signal.target),
            gross_rr=rr,
            risk_pct=float(account.risk_pct),
            risk_cash=risk_cash,
            equity=float(equity),
            volume=volume,
            current_spread_points=float(current_spread_points),
            normal_spread_median_points=float(spread.median_points or 0.0),
            normal_spread_p95_points=float(spread.p95_points or 0.0),
            spread_status=spread.status,
            spread_to_stop_ratio=spread.spread_to_stop_ratio,
            h4_gate=h4_gate,
            news_gate=news_gate,
            execution_mode="DEMO_ONLY",
            prepared_at_utc=now.isoformat(),
        )
        try:
            self.ledger.claim(ticket)
        except PermissionError:
            return DemoGateDecision(False, ("DUPLICATE_SIGNAL_ACCOUNT_ALREADY_CLAIMED",), None)
        return DemoGateDecision(True, (), ticket)


class DemoPostFillVerifier:
    """Verify the actual demo fill and protection after broker acknowledgement."""

    def verify(
        self,
        ticket: DemoExecutionTicket,
        *,
        actual_fill_price: float,
        actual_sl: float,
        actual_tp: float,
        fill_volume: float,
        contract: BrokerContract,
        max_risk_overrun_fraction: float = 0.10,
        sl_tp_tolerance_points: float = 1.5,
    ) -> FillVerification:
        reasons: list[str] = []
        point = contract.point if contract.point > 0 else contract.tick_size
        slippage_points = abs(float(actual_fill_price) - ticket.requested_entry) / point if point > 0 else float("inf")

        tol = max(point * sl_tp_tolerance_points, contract.tick_size)
        if abs(float(actual_sl) - ticket.stop) > tol:
            reasons.append("BROKER_SL_DOES_NOT_MATCH_AUTHORIZED_STOP")
        if abs(float(actual_tp) - ticket.target) > tol:
            reasons.append("BROKER_TP_DOES_NOT_MATCH_AUTHORIZED_TARGET")
        if fill_volume <= 0 or abs(float(fill_volume) - ticket.volume) > max(contract.volume_step / 2.0, 1e-12):
            reasons.append("BROKER_FILL_VOLUME_MISMATCH")

        effective_stop_distance = abs(float(actual_fill_price) - float(actual_sl))
        initial_stop_distance = abs(ticket.requested_entry - ticket.stop)
        if contract.loss_per_lot_at_stop is not None and contract.loss_per_lot_at_stop > 0 and initial_stop_distance > 0:
            per_lot = float(contract.loss_per_lot_at_stop) * (effective_stop_distance / initial_stop_distance)
            effective_risk_cash = per_lot * float(fill_volume)
        elif contract.tick_size > 0 and contract.tick_value > 0:
            effective_risk_cash = (effective_stop_distance / contract.tick_size) * contract.tick_value * float(fill_volume)
        else:
            effective_risk_cash = float("inf")
        effective_risk_pct = (effective_risk_cash / ticket.equity * 100.0) if ticket.equity > 0 else float("inf")
        if effective_risk_cash > ticket.risk_cash * (1.0 + max_risk_overrun_fraction):
            reasons.append("EFFECTIVE_RISK_EXCEEDS_AUTHORIZED_TOLERANCE")

        status = "PASS"
        if any(r.startswith("BROKER_SL_") or r.startswith("BROKER_TP_") for r in reasons):
            status = "CRITICAL_PROTECTION_REVIEW"
        elif reasons:
            status = "REVIEW_REQUIRED"

        return FillVerification(
            status=status,
            reasons=tuple(reasons),
            slippage_points=slippage_points,
            effective_risk_cash=effective_risk_cash,
            effective_risk_pct=effective_risk_pct,
            fill_volume=float(fill_volume),
            verified_at_utc=datetime.now(timezone.utc).isoformat(),
        )
