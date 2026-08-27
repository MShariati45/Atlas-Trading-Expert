from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from atlas.execution.models import AccountConfig


@dataclass(frozen=True, slots=True)
class AccountIdentityDecision:
    demo_verified: bool
    reasons: tuple[str, ...]
    login: int | None
    server: str
    trade_mode: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AccountIdentityVerifier:
    """Single definition of DEMO identity for authorization and transport.

    The authoritative live check is MT5 trade_mode. Server/account text is used
    only as defense-in-depth and can never override a REAL/LIVE trade_mode.
    """

    @staticmethod
    def server_looks_demo(server: str) -> bool:
        value = str(server or "").upper()
        return "DEMO" in value and "LIVE" not in value and "REAL" not in value

    @staticmethod
    def configured_looks_demo(account: AccountConfig) -> bool:
        value = " ".join([account.account_id or "", account.broker or ""]).upper()
        return "DEMO" in value and "LIVE" not in value and "REAL" not in value

    def from_preflight(self, account: AccountConfig, preflight: dict[str, Any]) -> AccountIdentityDecision:
        acct = preflight.get("account", {}) if isinstance(preflight, dict) else {}
        server = str(acct.get("server", ""))
        login = acct.get("login")
        trade_mode = acct.get("trade_mode")
        reasons: list[str] = []
        if not self.configured_looks_demo(account):
            reasons.append("CONFIGURED_ACCOUNT_NOT_POSITIVELY_DEMO")
        if not self.server_looks_demo(server):
            reasons.append("PREFLIGHT_SERVER_NOT_POSITIVELY_DEMO")
        return AccountIdentityDecision(not reasons, tuple(reasons), int(login) if login is not None else None, server, int(trade_mode) if trade_mode is not None else None)

    def from_mt5(self, account: AccountConfig, info: Any, mt5: Any, *, expected_login: int | None = None) -> AccountIdentityDecision:
        reasons: list[str] = []
        login = int(getattr(info, "login", 0) or 0)
        server = str(getattr(info, "server", "") or "")
        trade_mode = int(getattr(info, "trade_mode", -1))
        demo_mode = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
        real_mode = int(getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2))
        if trade_mode == real_mode or trade_mode != demo_mode:
            reasons.append("MT5_ACCOUNT_TRADE_MODE_NOT_DEMO")
        if not self.server_looks_demo(server):
            reasons.append("MT5_SERVER_NOT_POSITIVELY_DEMO")
        if expected_login is not None and login != int(expected_login):
            reasons.append("MT5_LOGIN_MISMATCH")
        if not bool(getattr(info, "trade_allowed", False)):
            reasons.append("MT5_ACCOUNT_TRADING_NOT_ALLOWED")
        if not bool(getattr(info, "trade_expert", False)):
            reasons.append("MT5_EXPERT_TRADING_NOT_ALLOWED")
        return AccountIdentityDecision(not reasons, tuple(reasons), login or None, server, trade_mode)
