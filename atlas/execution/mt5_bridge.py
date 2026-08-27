from __future__ import annotations
from dataclasses import dataclass
import os
from typing import Any
from .metatrader_bridge import MetaTraderBridge
from .models import AccountConfig, ApprovedSignal

class MetaTrader5Unavailable(RuntimeError):
    pass

@dataclass(slots=True)
class MT5ConnectionSettings:
    login: int | None = None
    password: str | None = None
    password_env: str | None = None
    server: str | None = None
    terminal_path: str | None = None
    symbol_map: dict[str, str] | None = None
    max_deviation_points: int = 20
    atlas_magic: int = 260826
    filling_mode_override: int | None = None

    def resolved_password(self) -> str | None:
        if self.password_env:
            return os.getenv(self.password_env)
        return self.password

class MT5PythonBridge(MetaTraderBridge):
    """Optional MetaTrader 5 Python adapter.

    Import is lazy so Atlas remains testable/provider-independent on machines
    without the MetaTrader5 package or a Windows MT5 terminal.
    """

    def __init__(self, settings_by_account: dict[str, MT5ConnectionSettings] | None = None, *, execution_enabled: bool = False) -> None:
        self.settings_by_account = settings_by_account or {}
        self.execution_enabled = bool(execution_enabled)
        self._mt5: Any = None

    def _require_execution_enabled(self) -> None:
        if not self.execution_enabled:
            raise PermissionError("MT5_EXECUTION_DISABLED")

    def _module(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except Exception as exc:
                raise MetaTrader5Unavailable("MetaTrader5 Python package/terminal is not available") from exc
            self._mt5 = mt5
        return self._mt5

    def connect(self, account: AccountConfig) -> None:
        mt5 = self._module()
        settings = self.settings_by_account.get(account.account_id, MT5ConnectionSettings())
        kwargs: dict[str, Any] = {}
        if settings.terminal_path:
            kwargs["path"] = settings.terminal_path
        if settings.login is not None:
            kwargs["login"] = settings.login
        resolved_password = settings.resolved_password()
        if resolved_password:
            kwargs["password"] = resolved_password
        if settings.server:
            kwargs["server"] = settings.server
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    def broker_symbol(self, account: AccountConfig, canonical_symbol: str) -> str:
        settings = self.settings_by_account.get(account.account_id, MT5ConnectionSettings())
        mapping = settings.symbol_map or {}
        return str(mapping.get(canonical_symbol, canonical_symbol))

    def place_order(self, account: AccountConfig, signal: ApprovedSignal, volume: float) -> str:
        """Legacy direct-order path is permanently disabled.

        New positions must flow through ControlledDemoExecutionGate and
        DemoOnlyMT5Transport so account identity, news, spread, risk,
        idempotency, and post-fill verification cannot be bypassed.
        """
        self._require_execution_enabled()
        raise PermissionError("LEGACY_DIRECT_ORDER_PATH_DISABLED_USE_DEMO_TRANSPORT")

    def modify_stop(self, account: AccountConfig, ticket: str, stop: float) -> None:
        self._require_execution_enabled()
        raise PermissionError("LEGACY_TRADE_MANAGEMENT_PATH_DISABLED_USE_SUPERVISED_DEMO_MANAGEMENT")

    def close_position(self, account: AccountConfig, ticket: str) -> None:
        self._require_execution_enabled()
        raise PermissionError("LEGACY_TRADE_MANAGEMENT_PATH_DISABLED_USE_SUPERVISED_DEMO_MANAGEMENT")

