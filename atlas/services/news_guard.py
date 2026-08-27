from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(slots=True, frozen=True)
class NewsEvent:
    event_id: str
    starts_at_utc: datetime
    affected_symbols: frozenset[str]
    impact: str = "HIGH"
    title: str = ""
    currencies: frozenset[str] = frozenset()
    source_name: str = ""
    source_url: str = ""
    blackout_before_minutes: int | None = None
    blackout_after_minutes: int = 0
    open_trade_review_minutes: int | None = None

@dataclass(slots=True)
class NewsAssessment:
    clear_for_new_entry: bool
    force_review_open_trade: bool
    blocking_event: NewsEvent | None
    reason_codes: list[str]

class NewsGuard:
    def __init__(self, pre_entry_blackout_minutes: int = 120, open_trade_review_minutes: int = 120) -> None:
        self.pre_entry_blackout = timedelta(minutes=pre_entry_blackout_minutes)
        self.open_trade_review = timedelta(minutes=open_trade_review_minutes)
        self._events: list[NewsEvent] = []

    def set_events(self, events: list[NewsEvent]) -> None:
        self._events = sorted(events, key=lambda e: e.starts_at_utc)

    def assess(self, symbol: str, now_utc: datetime | None = None) -> NewsAssessment:
        now = now_utc or datetime.now(timezone.utc)
        for event in self._events:
            if event.impact.upper() != "HIGH" or symbol not in event.affected_symbols:
                continue
            delta = event.starts_at_utc - now
            pre = timedelta(minutes=event.blackout_before_minutes) if event.blackout_before_minutes is not None else self.pre_entry_blackout
            post = timedelta(minutes=max(0, event.blackout_after_minutes))
            review = timedelta(minutes=event.open_trade_review_minutes) if event.open_trade_review_minutes is not None else self.open_trade_review
            if -post <= delta <= pre:
                return NewsAssessment(False, abs(delta) <= review, event, ["NEWS_BLACKOUT_ACTIVE"])
            if timedelta(0) <= delta <= review:
                return NewsAssessment(True, True, event, ["OPEN_TRADE_NEWS_REVIEW_REQUIRED"])
        return NewsAssessment(True, False, None, ["NEWS_CLEAR"])
