
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class PaperTrade:
    symbol: str
    signal_time: str
    direction: str
    agent: str
    fib_depth: float
    fib_zone: str
    entry: float
    stop: float
    target: float
    quality_score: float
    decision: str
    reject_reason: str = ""
    outcome: str = "UNRESOLVED"
    realized_r: Optional[float] = None
    mae_r: Optional[float] = None
    mfe_r: Optional[float] = None
    be_triggered: bool = False
    exit_time: str = ""
    exit_price: Optional[float] = None

    def to_dict(self):
        return asdict(self)
