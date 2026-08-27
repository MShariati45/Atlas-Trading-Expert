from __future__ import annotations

from typing import Any

from atlas.api.read_models import AtlasReadModelService
from atlas.security import AccessPolicy, UserIdentity, UserRole
from atlas.security.auth_store import SQLiteAuthStore
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.staging.leads import LeadStore


class AtlasPrivateAppService:
    """Application boundary used by the private web/API layer.

    Deliberately contains no MT5 bridge, order transport, or execution imports.
    The web application can read authorized state and manage identity/H4 approval
    workflows, but cannot create or mutate broker orders directly.
    """

    def __init__(self, *, auth: SQLiteAuthStore, leads: LeadStore,
                 read_models: AtlasReadModelService | None = None,
                 h4_approvals: H4HumanApprovalStore | None = None) -> None:
        self.auth = auth
        self.leads = leads
        self.read_models = read_models or AtlasReadModelService()
        self.h4_approvals = h4_approvals or H4HumanApprovalStore()

    @staticmethod
    def identity_payload(user: UserIdentity) -> dict[str, Any]:
        return {"user_id": user.user_id, "username": user.username, "role": user.role.value,
                "enabled": user.enabled, "account_ids": sorted(user.account_ids)}

    def list_users(self, actor: UserIdentity) -> list[dict[str, Any]]:
        if actor.role not in {UserRole.OWNER, UserRole.ADMIN} or not actor.enabled:
            raise PermissionError("owner/admin role required")
        return [self.identity_payload(x) for x in self.auth.list_users()]

    def visible_account_ids(self, actor: UserIdentity) -> list[str]:
        if actor.role is UserRole.TRADER:
            return sorted(actor.account_ids)
        ids: set[str] = set()
        for user in self.auth.list_users():
            ids.update(user.account_ids)
        # Owner/Admin dashboard also surfaces the locally connected read-only MT5
        # snapshot even before a Trader assignment exists. This does not grant
        # execution authority; it only makes the operational account visible.
        state = self.read_models.dashboard_state()
        current = state.get("account", {}) if isinstance(state.get("account"), dict) else {}
        connected_id = str(current.get("account_id") or current.get("login") or "").strip()
        if connected_id and current.get("status") != "UNAVAILABLE":
            ids.add(connected_id)
        return sorted(ids)

    def list_accounts(self, actor: UserIdentity) -> list[dict[str, Any]]:
        # Compatibility/read-only identity view retained for existing callers.
        return [{"account_id": aid, "read_only": actor.role is UserRole.TRADER} for aid in self.visible_account_ids(actor)]

    def list_account_summaries(self, actor: UserIdentity) -> list[dict[str, Any]]:
        return [self.read_models.account_summary(actor, aid) for aid in self.visible_account_ids(actor)]

    def account_detail(self, actor: UserIdentity, account_id: str) -> dict[str, Any]:
        return self.read_models.account_summary(actor, account_id)

    def dashboard(self, actor: UserIdentity) -> dict[str, Any]:
        if actor.role is UserRole.TRADER:
            accounts = self.list_account_summaries(actor)
            return {"role": actor.role.value, "accounts": accounts, "account_count": len(accounts), "read_only": True}
        return self.read_models.owner_dashboard(actor, self.visible_account_ids(actor))

    def watchlist(self, actor: UserIdentity) -> list[dict[str, Any]]:
        if not actor.enabled:
            raise PermissionError("user disabled")
        return self.read_models.watchlist()

    def list_leads(self, actor: UserIdentity) -> list[dict[str, Any]]:
        if actor.role not in {UserRole.OWNER, UserRole.ADMIN} or not actor.enabled:
            raise PermissionError("owner/admin role required")
        return [x.to_dict() for x in self.leads.list_all()]

    def create_user(self, actor: UserIdentity, *, username: str, password: str, role: str,
                    account_ids: list[str] | None = None, mfa_secret_hex: str = "") -> dict[str, Any]:
        if not AccessPolicy.can_manage_users(actor):
            raise PermissionError("owner role required")
        parsed_role = UserRole(role.upper())
        secret = bytes.fromhex(mfa_secret_hex) if mfa_secret_hex else None
        user = self.auth.create_user(actor=actor, username=username, password=password, role=parsed_role,
                                    account_ids=account_ids or (), mfa_secret=secret)
        return self.identity_payload(user)

    def assign_account(self, actor: UserIdentity, *, trader_user_id: str, account_id: str) -> dict[str, Any]:
        user = self.auth.assign_account(actor=actor, trader_user_id=trader_user_id, account_id=account_id)
        return self.identity_payload(user)

    def set_user_enabled(self, actor: UserIdentity, *, user_id: str, enabled: bool) -> dict[str, Any]:
        user = self.auth.set_enabled(actor=actor, user_id=user_id, enabled=enabled)
        return self.identity_payload(user)

    def approve_h4(self, actor: UserIdentity, *, symbol: str, trend: str, impulse_start: float | None,
                   impulse_end: float | None, note: str = "", structure_token: str | None = None) -> dict[str, Any]:
        if not AccessPolicy.can_modify_strategy(actor):
            raise PermissionError("owner/admin role required")
        approval = self.h4_approvals.approve(symbol, trend, impulse_start, impulse_end, note,
                                             structure_token=structure_token)
        return self.h4_approvals.dashboard_state(symbol, {"trend": trend})
