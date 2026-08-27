from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from atlas.execution.account_identity import AccountIdentityDecision


class ExecutionConnectionState(str, Enum):
    CONNECTED = "CONNECTED"
    OBSERVATION = "OBSERVATION"
    DEMO_AUTHORIZED = "DEMO_AUTHORIZED"
    EXECUTION_ENABLED = "EXECUTION_ENABLED"


@dataclass(frozen=True, slots=True)
class AccountExecutionState:
    """Explicit per-account lifecycle with recorded authoritative DEMO identity."""

    account_id: str
    state: ExecutionConnectionState = ExecutionConnectionState.CONNECTED
    demo_verified: bool = False
    safety_passed: bool = False
    verified_login: int | None = None
    verified_server: str | None = None
    verified_trade_mode: int | None = None
    identity_checked_at_utc: str | None = None

    def to_observation(self) -> "AccountExecutionState":
        if self.state is not ExecutionConnectionState.CONNECTED:
            raise ValueError("OBSERVATION requires CONNECTED state")
        return replace(self, state=ExecutionConnectionState.OBSERVATION)

    def authorize_demo(self, *, identity: AccountIdentityDecision, safety_passed: bool) -> "AccountExecutionState":
        if self.state is not ExecutionConnectionState.OBSERVATION:
            raise ValueError("DEMO_AUTHORIZED requires OBSERVATION state")
        if not identity.demo_verified:
            raise PermissionError("authoritative demo account verification required")
        if not safety_passed:
            raise PermissionError("all demo safety gates must pass")
        return replace(
            self,
            state=ExecutionConnectionState.DEMO_AUTHORIZED,
            demo_verified=True,
            safety_passed=True,
            verified_login=identity.login,
            verified_server=identity.server,
            verified_trade_mode=identity.trade_mode,
            identity_checked_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    def enable_execution(self, *, explicit_demo_unlock: bool) -> "AccountExecutionState":
        if self.state is not ExecutionConnectionState.DEMO_AUTHORIZED:
            raise ValueError("EXECUTION_ENABLED requires DEMO_AUTHORIZED state")
        if not self.demo_verified or not self.safety_passed or not explicit_demo_unlock:
            raise PermissionError("explicit demo unlock and verified safety state required")
        if not self.identity_checked_at_utc or self.verified_trade_mode is None:
            raise PermissionError("fresh authoritative MT5 identity required before execution enablement")
        return replace(self, state=ExecutionConnectionState.EXECUTION_ENABLED)

    def lock(self) -> "AccountExecutionState":
        return replace(self, state=ExecutionConnectionState.OBSERVATION, safety_passed=False)
