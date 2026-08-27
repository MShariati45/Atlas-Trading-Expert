from dataclasses import dataclass

@dataclass(slots=True)
class AccountConfig:
    account_id: str
    enabled: bool
    risk_pct: float
    target_r: float = 2.0
    broker: str = ""

@dataclass(slots=True)
class ApprovedSignal:
    signal_id: str
    symbol: str
    direction: str
    entry: float
    stop: float
    target: float
