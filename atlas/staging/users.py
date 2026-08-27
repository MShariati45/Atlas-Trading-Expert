from __future__ import annotations

from dataclasses import replace

from atlas.accounts.assignments import TraderAccountAssignmentService
from atlas.security import AccessPolicy, UserIdentity, UserRole


class StagingUserService:
    """Policy layer for the approved Owner/Admin/Trader access model."""

    @staticmethod
    def can_create_user(actor: UserIdentity) -> bool:
        return AccessPolicy.can_manage_users(actor)

    @staticmethod
    def can_assign_account(actor: UserIdentity) -> bool:
        return AccessPolicy.can_manage_accounts(actor)

    @staticmethod
    def assign_account(actor: UserIdentity, trader: UserIdentity, account_id: str) -> UserIdentity:
        return TraderAccountAssignmentService.assign(actor, trader, account_id)

    @staticmethod
    def unassign_account(actor: UserIdentity, trader: UserIdentity, account_id: str) -> UserIdentity:
        return TraderAccountAssignmentService.unassign(actor, trader, account_id)

    @staticmethod
    def suspend(actor: UserIdentity, target: UserIdentity) -> UserIdentity:
        if not AccessPolicy.can_manage_users(actor):
            raise PermissionError("owner role required")
        if target.role is UserRole.OWNER and target.user_id == actor.user_id:
            raise PermissionError("owner cannot self-suspend through this action")
        return replace(target, enabled=False)
