from __future__ import annotations

from dataclasses import dataclass

from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.risk.position_sizing import risk_amount


@dataclass(frozen=True, slots=True)
class AccountExecutionPlan:
    account_id: str
    broker: str
    enabled: bool
    symbol: str
    direction: str
    entry: float
    stop: float
    target: float
    risk_pct: float
    risk_cash: float


class MultiAccountExecutionPlanner:
    """Build independent account-level plans from one approved Atlas signal.

    This module does not send orders. It preserves account isolation so the same
    strategy signal can later be routed to multiple MT5 terminals/accounts while
    each account retains its own equity and risk percentage.
    """

    def build(self, signal: ApprovedSignal, accounts: list[AccountConfig], equity_by_account: dict[str, float]) -> list[AccountExecutionPlan]:
        plans: list[AccountExecutionPlan] = []
        for account in accounts:
            if not account.enabled:
                continue
            if account.account_id not in equity_by_account:
                raise ValueError(f"missing equity for account {account.account_id}")
            equity = float(equity_by_account[account.account_id])
            if equity <= 0:
                raise ValueError(f"equity must be positive for account {account.account_id}")
            plans.append(AccountExecutionPlan(
                account_id=account.account_id,
                broker=account.broker,
                enabled=True,
                symbol=signal.symbol,
                direction=signal.direction,
                entry=signal.entry,
                stop=signal.stop,
                target=signal.target,
                risk_pct=float(account.risk_pct),
                risk_cash=risk_amount(equity, float(account.risk_pct)),
            ))
        return plans
