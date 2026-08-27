from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ManagedAccountProfile:
    account_id: str
    owner_user_id: str
    display_name: str
    broker: str
    terminal_instance_id: str
    enabled: bool = True
    risk_pct: float = 0.5
    report_namespace: str = ""
    privacy_alias: str = ""

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("account_id required")
        if not self.owner_user_id.strip():
            raise ValueError("owner_user_id required")
        if not self.terminal_instance_id.strip():
            raise ValueError("terminal_instance_id required")
        if self.risk_pct <= 0:
            raise ValueError("risk_pct must be positive")

    @property
    def namespace(self) -> str:
        return self.report_namespace or self.account_id

    @property
    def safe_alias(self) -> str:
        return self.privacy_alias or f"ACCOUNT-{self.account_id[-4:]}"
