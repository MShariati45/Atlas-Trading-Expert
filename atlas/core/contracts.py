from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"

@dataclass(slots=True)
class ReportEnvelope:
    agent_id: str
    symbol: str
    timeframe: str
    status: str
    confidence: float
    data: dict[str, Any]
    reason_codes: list[str] = field(default_factory=list)
    event_time_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    schema_version: str = SCHEMA_VERSION
    state_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
