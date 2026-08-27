from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import struct
import time
from typing import Iterable

from atlas.security.access_control import PasswordHasher, PasswordRecord, UserIdentity, UserRole


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthSession:
    token: str
    csrf_token: str
    user: UserIdentity
    expires_at_epoch: int


class TOTP:
    """Small RFC-6238-compatible SHA-1 TOTP helper using only stdlib.

    Secrets are raw bytes. Enrollment/presentation is deliberately kept outside
    this module so the API layer never needs to expose a secret after setup.
    """

    @staticmethod
    def generate_secret() -> bytes:
        return secrets.token_bytes(20)

    @staticmethod
    def code(secret: bytes, *, at_epoch: int | None = None, step: int = 30, digits: int = 6) -> str:
        at_epoch = int(time.time()) if at_epoch is None else int(at_epoch)
        counter = at_epoch // step
        msg = struct.pack(">Q", counter)
        digest = hmac.new(secret, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = ((digest[offset] & 0x7F) << 24) | (digest[offset + 1] << 16) | (digest[offset + 2] << 8) | digest[offset + 3]
        return str(binary % (10 ** digits)).zfill(digits)

    @staticmethod
    def verify(secret: bytes, code: str, *, at_epoch: int | None = None, window: int = 1) -> bool:
        if not code or not code.isdigit():
            return False
        now = int(time.time()) if at_epoch is None else int(at_epoch)
        return any(hmac.compare_digest(TOTP.code(secret, at_epoch=now + offset * 30), code) for offset in range(-window, window + 1))


class SQLiteAuthStore:
    """Transactional user/session store for the staging/private Atlas app.

    Session bearer tokens are never stored in plaintext. Owner/Admin accounts
    can be configured to require TOTP MFA. Account assignments are stored here
    as access-control metadata only and never change MT5/execution state.
    """

    def __init__(self, path: str | Path = "runtime/atlas_auth.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    role TEXT NOT NULL CHECK(role IN ('OWNER','ADMIN','TRADER')),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    password_salt_hex TEXT NOT NULL,
                    password_digest_hex TEXT NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    mfa_required INTEGER NOT NULL DEFAULT 0,
                    mfa_secret_hex TEXT,
                    created_at_utc TEXT NOT NULL,
                    password_changed_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_accounts (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    account_id TEXT NOT NULL,
                    PRIMARY KEY(user_id, account_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    csrf_hash TEXT NOT NULL,
                    created_at_epoch INTEGER NOT NULL,
                    expires_at_epoch INTEGER NOT NULL,
                    last_seen_epoch INTEGER NOT NULL,
                    ip TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    ip TEXT NOT NULL DEFAULT '',
                    detail_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )

    def _event(self, event_type: str, *, username: str = "", user_id: str = "", ip: str = "", detail: dict | None = None) -> None:
        with self._connect() as c:
            c.execute(
                "INSERT INTO security_events(created_at_utc,event_type,username,user_id,ip,detail_json) VALUES(?,?,?,?,?,?)",
                (_utc_now(), event_type, username, user_id, ip, json.dumps(detail or {}, separators=(",", ":"))),
            )

    def create_user(self, *, actor: UserIdentity | None, username: str, password: str, role: UserRole, account_ids: Iterable[str] = (), require_mfa: bool | None = None, mfa_secret: bytes | None = None) -> UserIdentity:
        username = username.strip()
        if not username:
            raise ValueError("username required")
        if actor is not None and actor.role is not UserRole.OWNER:
            raise PermissionError("owner role required")
        if actor is None and self.count_users() != 0:
            raise PermissionError("bootstrap creation allowed only for empty store")
        record = PasswordHasher.hash_password(password)
        require_mfa = (role in {UserRole.OWNER, UserRole.ADMIN}) if require_mfa is None else bool(require_mfa)
        if require_mfa and mfa_secret is None:
            raise ValueError("mfa_secret required when MFA is required")
        user_id = f"USR-{secrets.token_hex(8).upper()}"
        now = _utc_now()
        aids = sorted({str(x).strip() for x in account_ids if str(x).strip()})
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "INSERT INTO users(user_id,username,role,enabled,password_salt_hex,password_digest_hex,password_iterations,mfa_required,mfa_secret_hex,created_at_utc,password_changed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, username, role.value, 1, record.salt_hex, record.digest_hex, record.iterations, int(require_mfa), mfa_secret.hex() if mfa_secret else None, now, now),
            )
            for aid in aids:
                c.execute("INSERT INTO user_accounts(user_id,account_id) VALUES(?,?)", (user_id, aid))
            c.execute("COMMIT")
        return UserIdentity(user_id=user_id, username=username, role=role, account_ids=frozenset(aids), enabled=True)

    def count_users(self) -> int:
        with self._connect() as c:
            return int(c.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def get_user(self, user_id: str) -> UserIdentity | None:
        with self._connect() as c:
            row = c.execute("SELECT user_id,username,role,enabled FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return None
            aids = frozenset(r[0] for r in c.execute("SELECT account_id FROM user_accounts WHERE user_id=? ORDER BY account_id", (user_id,)))
        return UserIdentity(row["user_id"], row["username"], UserRole(row["role"]), aids, bool(row["enabled"]))

    def get_user_by_username(self, username: str) -> tuple[UserIdentity, PasswordRecord, bool, bytes | None] | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
            if not row:
                return None
            aids = frozenset(r[0] for r in c.execute("SELECT account_id FROM user_accounts WHERE user_id=? ORDER BY account_id", (row["user_id"],)))
        identity = UserIdentity(row["user_id"], row["username"], UserRole(row["role"]), aids, bool(row["enabled"]))
        password = PasswordRecord(row["password_salt_hex"], row["password_digest_hex"], int(row["password_iterations"]))
        secret = bytes.fromhex(row["mfa_secret_hex"]) if row["mfa_secret_hex"] else None
        return identity, password, bool(row["mfa_required"]), secret

    def authenticate(self, *, username: str, password: str, mfa_code: str = "", ip: str = "", user_agent: str = "", ttl_seconds: int = 8 * 3600) -> AuthSession | None:
        found = self.get_user_by_username(username)
        # Do fixed PBKDF2 work even for unknown usernames to reduce trivial timing leaks.
        if found is None:
            dummy = PasswordHasher.hash_password("A" * 16, iterations=50_000)
            PasswordHasher.verify(password, dummy)
            self._event("LOGIN_FAILED", username=username.strip(), ip=ip, detail={"reason": "INVALID_CREDENTIALS"})
            return None
        identity, record, mfa_required, secret = found
        if not identity.enabled or not PasswordHasher.verify(password, record):
            self._event("LOGIN_FAILED", username=identity.username, user_id=identity.user_id, ip=ip, detail={"reason": "INVALID_CREDENTIALS_OR_DISABLED"})
            return None
        if mfa_required and (secret is None or not TOTP.verify(secret, mfa_code)):
            self._event("LOGIN_FAILED", username=identity.username, user_id=identity.user_id, ip=ip, detail={"reason": "MFA_REQUIRED_OR_INVALID"})
            return None
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        now = int(time.time())
        expires = now + max(300, min(int(ttl_seconds), 24 * 3600))
        with self._connect() as c:
            c.execute("INSERT INTO sessions(session_hash,user_id,csrf_hash,created_at_epoch,expires_at_epoch,last_seen_epoch,ip,user_agent,revoked) VALUES(?,?,?,?,?,?,?,?,0)", (_sha256(token), identity.user_id, _sha256(csrf), now, expires, now, ip, user_agent[:512]))
        self._event("LOGIN_SUCCESS", username=identity.username, user_id=identity.user_id, ip=ip)
        return AuthSession(token, csrf, identity, expires)

    def resolve_session(self, token: str, *, touch: bool = True) -> UserIdentity | None:
        if not token:
            return None
        now = int(time.time())
        with self._connect() as c:
            row = c.execute("SELECT user_id,expires_at_epoch,revoked FROM sessions WHERE session_hash=?", (_sha256(token),)).fetchone()
            if not row or row["revoked"] or int(row["expires_at_epoch"]) <= now:
                return None
            user = self.get_user(row["user_id"])
            if not user or not user.enabled:
                return None
            if touch:
                c.execute("UPDATE sessions SET last_seen_epoch=? WHERE session_hash=?", (now, _sha256(token)))
            return user

    def validate_csrf(self, token: str, csrf: str) -> bool:
        if not token or not csrf:
            return False
        with self._connect() as c:
            row = c.execute("SELECT csrf_hash,expires_at_epoch,revoked FROM sessions WHERE session_hash=?", (_sha256(token),)).fetchone()
        return bool(row and not row["revoked"] and int(row["expires_at_epoch"]) > int(time.time()) and hmac.compare_digest(row["csrf_hash"], _sha256(csrf)))

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        with self._connect() as c:
            row = c.execute("SELECT user_id FROM sessions WHERE session_hash=?", (_sha256(token),)).fetchone()
            c.execute("UPDATE sessions SET revoked=1 WHERE session_hash=?", (_sha256(token),))
        if row:
            self._event("LOGOUT", user_id=row["user_id"])

    def revoke_user_sessions(self, user_id: str) -> None:
        with self._connect() as c:
            c.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))
        self._event("SESSIONS_REVOKED", user_id=user_id)

    def set_enabled(self, *, actor: UserIdentity, user_id: str, enabled: bool) -> UserIdentity:
        if actor.role is not UserRole.OWNER:
            raise PermissionError("owner role required")
        if actor.user_id == user_id and not enabled:
            raise PermissionError("owner cannot self-suspend")
        with self._connect() as c:
            c.execute("UPDATE users SET enabled=? WHERE user_id=?", (int(enabled), user_id))
            if c.total_changes == 0:
                raise KeyError(user_id)
        if not enabled:
            self.revoke_user_sessions(user_id)
        user = self.get_user(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def assign_account(self, *, actor: UserIdentity, trader_user_id: str, account_id: str) -> UserIdentity:
        if actor.role is not UserRole.OWNER:
            raise PermissionError("owner role required")
        trader = self.get_user(trader_user_id)
        if trader is None or trader.role is not UserRole.TRADER:
            raise ValueError("TRADER user required")
        aid = account_id.strip()
        if not aid:
            raise ValueError("account_id required")
        with self._connect() as c:
            c.execute("INSERT OR IGNORE INTO user_accounts(user_id,account_id) VALUES(?,?)", (trader_user_id, aid))
        return self.get_user(trader_user_id)  # type: ignore[return-value]

    def list_users(self) -> list[UserIdentity]:
        with self._connect() as c:
            rows = c.execute("SELECT user_id,username,role,enabled FROM users ORDER BY created_at_utc").fetchall()
            accounts = c.execute("SELECT user_id,account_id FROM user_accounts ORDER BY user_id,account_id").fetchall()
        by_user: dict[str, set[str]] = {}
        for row in accounts:
            by_user.setdefault(str(row[0]), set()).add(str(row[1]))
        return [UserIdentity(user_id=str(r[0]), username=str(r[1]), role=UserRole(str(r[2])),
                             account_ids=frozenset(by_user.get(str(r[0]), set())), enabled=bool(r[3])) for r in rows]

    def session_info(self, token: str) -> dict | None:
        session_hash = _sha256(token)
        with self._connect() as c:
            row = c.execute("SELECT created_at_epoch,expires_at_epoch,last_seen_epoch,ip,user_agent,revoked FROM sessions WHERE session_hash=?", (session_hash,)).fetchone()
        if row is None:
            return None
        return {"created_at_epoch": int(row[0]), "expires_at_epoch": int(row[1]), "last_seen_epoch": int(row[2]),
                "ip": str(row[3]), "user_agent": str(row[4]), "revoked": bool(row[5])}

    def list_security_events(self, *, limit: int = 100) -> list[dict]:
        with self._connect() as c:
            rows = c.execute("SELECT created_at_utc,event_type,username,user_id,ip,detail_json FROM security_events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [{"created_at_utc": r[0], "event_type": r[1], "username": r[2], "user_id": r[3], "ip": r[4], "detail": json.loads(r[5])} for r in rows]
