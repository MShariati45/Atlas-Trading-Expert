from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from atlas.execution.account_identity import AccountIdentityVerifier
from atlas.execution.models import AccountConfig
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger


@dataclass(frozen=True, slots=True)
class AccountRiskSnapshot:
    available: bool
    trades_today: int
    symbol_trades_today: int
    daily_risk_used_pct: float
    open_symbol_position: bool
    reasons: tuple[str, ...] = ()


class AccountRiskStateService(Protocol):
    def snapshot(self, account: AccountConfig, symbol: str, now: datetime) -> AccountRiskSnapshot: ...


class StaticAccountRiskStateService:
    """Tests/offline self-check only. Production should use MT5AccountRiskStateService."""
    def __init__(self, snapshot: AccountRiskSnapshot | None = None) -> None:
        self.value = snapshot or AccountRiskSnapshot(True, 0, 0, 0.0, False)
    def snapshot(self, account: AccountConfig, symbol: str, now: datetime) -> AccountRiskSnapshot:
        return self.value


class MT5AccountRiskStateService:
    """Authoritative daily-risk state from SQLite plus current MT5 positions.

    Daily boundaries default to America/Vancouver. Any inability to verify the
    DEMO terminal or inspect positions fails closed.
    """
    def __init__(self, ledger: SQLiteExecutionLedger, bridge: Any, *, timezone_name: str = "America/Vancouver") -> None:
        self.ledger = ledger
        self.bridge = bridge
        self.zone = ZoneInfo(timezone_name)
        self.identity = AccountIdentityVerifier()

    def _day_bounds_utc(self, now: datetime) -> tuple[datetime, datetime]:
        local = now.astimezone(self.zone)
        start_local = datetime.combine(local.date(), time.min, self.zone)
        end_local = datetime.combine(local.date().fromordinal(local.date().toordinal() + 1), time.min, self.zone)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def snapshot(self, account: AccountConfig, symbol: str, now: datetime) -> AccountRiskSnapshot:
        reasons: list[str] = []
        try:
            self.bridge.connect(account)
            mt5 = self.bridge._module()
            info = mt5.account_info()
            if info is None:
                return AccountRiskSnapshot(False, 0, 0, 0.0, False, ("MT5_ACCOUNT_INFO_UNAVAILABLE_FOR_RISK_STATE",))
            identity = self.identity.from_mt5(account, info, mt5)
            if not identity.demo_verified:
                return AccountRiskSnapshot(False, 0, 0, 0.0, False, tuple(identity.reasons))
            settings = self.bridge.settings_by_account.get(account.account_id)
            broker_symbol = str((settings.symbol_map if settings and settings.symbol_map else {}).get(symbol, symbol))
            positions = mt5.positions_get() or ()
            open_symbol = any(str(getattr(p, "symbol", "")) == broker_symbol for p in positions)
        except Exception as exc:
            reasons.append(f"MT5_POSITION_STATE_UNAVAILABLE:{type(exc).__name__}")
            return AccountRiskSnapshot(False, 0, 0, 0.0, False, tuple(reasons))
        start, end = self._day_bounds_utc(now)
        summary = self.ledger.daily_summary(account.account_id, symbol, start, end)
        return AccountRiskSnapshot(
            True,
            int(summary["trades_today"]),
            int(summary["symbol_trades_today"]),
            float(summary["daily_risk_used_pct"]),
            open_symbol,
            (),
        )
