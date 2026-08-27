from dataclasses import dataclass, asdict
from typing import Any

@dataclass(slots=True)
class JournalRecord:
    record_type: str
    payload: dict[str, Any]

class JournalStore:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, record: JournalRecord) -> None:
        self.records.append(asdict(record))
