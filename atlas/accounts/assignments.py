from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Any

from atlas.accounts.profiles import ManagedAccountProfile
from atlas.security import AccessPolicy, UserIdentity, UserRole


@dataclass(frozen=True, slots=True)
class TraderAccountSummary:
    account_id: str
    display_name: str
    broker: str
    enabled: bool
    balance: float | None = None
    equity: float | None = None
    today_pl: float | None = None
    open_trades: int | None = None


class TraderAccountAssignmentService:
    """Owner-controlled 1 Trader -> N MT5 account assignment model.

    Assignment changes are identity/access changes only. They never connect MT5,
    alter trading rules, or enable execution. Trader access remains read-only.
    """

    @staticmethod
    def assign(actor: UserIdentity, trader: UserIdentity, account_id: str) -> UserIdentity:
        if not AccessPolicy.can_manage_accounts(actor):
            raise PermissionError("owner role required")
        if trader.role is not UserRole.TRADER:
            raise ValueError("accounts can be assigned only to TRADER users")
        aid = str(account_id).strip()
        if not aid:
            raise ValueError("account_id required")
        return replace(trader, account_ids=frozenset(set(trader.account_ids) | {aid}))

    @staticmethod
    def unassign(actor: UserIdentity, trader: UserIdentity, account_id: str) -> UserIdentity:
        if not AccessPolicy.can_manage_accounts(actor):
            raise PermissionError("owner role required")
        if trader.role is not UserRole.TRADER:
            raise ValueError("accounts can be unassigned only from TRADER users")
        aid = str(account_id).strip()
        return replace(trader, account_ids=frozenset(x for x in trader.account_ids if x != aid))

    @staticmethod
    def assigned_profiles(trader: UserIdentity, accounts: Iterable[ManagedAccountProfile]) -> tuple[ManagedAccountProfile, ...]:
        if trader.role is not UserRole.TRADER:
            raise ValueError("TRADER user required")
        by_id = {a.account_id: a for a in accounts}
        return tuple(by_id[aid] for aid in sorted(trader.account_ids) if aid in by_id)

    @staticmethod
    def validate_switch(trader: UserIdentity, requested_account_id: str) -> str:
        aid = str(requested_account_id).strip()
        if not AccessPolicy.can_view_account(trader, aid):
            raise PermissionError("account is not assigned to this trader")
        return aid

    @staticmethod
    def build_read_only_summaries(
        trader: UserIdentity,
        accounts: Iterable[ManagedAccountProfile],
        runtime_by_account: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[TraderAccountSummary, ...]:
        runtime_by_account = runtime_by_account or {}
        out: list[TraderAccountSummary] = []
        for account in TraderAccountAssignmentService.assigned_profiles(trader, accounts):
            row = runtime_by_account.get(account.account_id, {})
            out.append(TraderAccountSummary(
                account_id=account.account_id,
                display_name=account.display_name,
                broker=account.broker,
                enabled=account.enabled,
                balance=_optional_float(row.get("balance")),
                equity=_optional_float(row.get("equity")),
                today_pl=_optional_float(row.get("today_pl")),
                open_trades=_optional_int(row.get("open_trades")),
            ))
        return tuple(out)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
