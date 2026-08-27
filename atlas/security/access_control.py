from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib, hmac, secrets


class UserRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    TRADER = "TRADER"

    # Internal migration aliases only; not exposed in the Atlas UI.
    ACCOUNT_OWNER = "TRADER"
    TRAINING_VIEWER = "TRADER"


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: str
    username: str
    role: UserRole
    account_ids: frozenset[str] = frozenset()
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class PasswordRecord:
    salt_hex: str
    digest_hex: str
    iterations: int = 310_000


class PasswordHasher:
    @staticmethod
    def hash_password(password: str, *, iterations: int = 310_000) -> PasswordRecord:
        if len(password) < 12:
            raise ValueError("password must be at least 12 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return PasswordRecord(salt.hex(), digest.hex(), iterations)

    @staticmethod
    def verify(password: str, record: PasswordRecord) -> bool:
        salt = bytes.fromhex(record.salt_hex)
        expected = bytes.fromhex(record.digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, record.iterations)
        return hmac.compare_digest(actual, expected)


class AccessPolicy:
    """Server-side authorization for the approved Owner/Admin/Trader model.

    UI visibility is never treated as authorization. Sensitive actions must call
    these policy methods (or equivalent server-side checks) again.
    """

    @staticmethod
    def can_view_account(user: UserIdentity, account_id: str) -> bool:
        if not user.enabled:
            return False
        if user.role in {UserRole.OWNER, UserRole.ADMIN}:
            return True
        if user.role is UserRole.TRADER:
            return account_id in user.account_ids
        return False

    @staticmethod
    def can_control_account(user: UserIdentity, account_id: str) -> bool:
        # Traders are read-only. Admin can perform operational actions on existing
        # accounts; Owner alone can create/attach/remove customer accounts.
        return user.enabled and user.role in {UserRole.OWNER, UserRole.ADMIN} and AccessPolicy.can_view_account(user, account_id)

    @staticmethod
    def can_manage_users(user: UserIdentity) -> bool:
        return user.enabled and user.role is UserRole.OWNER

    @staticmethod
    def can_manage_accounts(user: UserIdentity) -> bool:
        return user.enabled and user.role is UserRole.OWNER

    @staticmethod
    def can_modify_strategy(user: UserIdentity) -> bool:
        return user.enabled and user.role in {UserRole.OWNER, UserRole.ADMIN}

    @staticmethod
    def can_change_risk_or_execution(user: UserIdentity) -> bool:
        return user.enabled and user.role in {UserRole.OWNER, UserRole.ADMIN}

    @staticmethod
    def can_view_research(user: UserIdentity) -> bool:
        return user.enabled and user.role in {UserRole.OWNER, UserRole.ADMIN}

    @staticmethod
    def can_download_account_report(user: UserIdentity, account_id: str) -> bool:
        return AccessPolicy.can_view_account(user, account_id)

    @staticmethod
    def can_view_training(user: UserIdentity) -> bool:
        # Compatibility shim: the production UI does not expose a training role.
        return user.enabled and user.role in {UserRole.OWNER, UserRole.ADMIN}
