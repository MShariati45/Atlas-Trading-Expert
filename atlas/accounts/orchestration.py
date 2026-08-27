from __future__ import annotations
from dataclasses import dataclass
from .profiles import ManagedAccountProfile

@dataclass(frozen=True, slots=True)
class AccountWorkerSpec:
    account_id: str
    terminal_instance_id: str
    isolation_mode: str = "ONE_PROCESS_PER_TERMINAL_ACCOUNT"

class MultiTerminalAccountOrchestrator:
    """Builds isolated worker specifications for future multi-terminal operation.

    MetaTrader5's Python binding is terminal-session oriented. Atlas therefore does
    not multiplex multiple live MT5 accounts through one shared bridge session.
    Each enabled account receives an isolated process/worker bound to one terminal
    instance. Shared strategy signals are immutable inputs to those workers.
    """
    def build_worker_specs(self, accounts: list[ManagedAccountProfile]) -> list[AccountWorkerSpec]:
        seen_accounts: set[str] = set()
        seen_terminals: set[str] = set()
        specs: list[AccountWorkerSpec] = []
        for account in accounts:
            if not account.enabled:
                continue
            if account.account_id in seen_accounts:
                raise ValueError(f"duplicate account_id: {account.account_id}")
            if account.terminal_instance_id in seen_terminals:
                raise ValueError(f"terminal instance reused by multiple accounts: {account.terminal_instance_id}")
            seen_accounts.add(account.account_id)
            seen_terminals.add(account.terminal_instance_id)
            specs.append(AccountWorkerSpec(account.account_id, account.terminal_instance_id))
        return specs
