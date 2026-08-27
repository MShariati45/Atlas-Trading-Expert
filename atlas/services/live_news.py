from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from atlas.services.news_guard import NewsAssessment, NewsGuard
from atlas.services.news_provider import ScheduledNewsProvider, NewsProviderStatus


@dataclass(slots=True)
class LiveNewsResult:
    assessment: NewsAssessment | None
    provider_status: NewsProviderStatus
    gate: bool | None
    reason_codes: list[str]


class LiveNewsGuardService:
    """Refreshes NewsGuard from a provider and returns a tri-state hard gate.

    True = data available and clear; False = blocking event; None = news data
    unavailable, therefore Supervisor must WAIT rather than assume safety.
    """

    def __init__(self, provider: ScheduledNewsProvider, guard: NewsGuard | None = None) -> None:
        self.provider = provider
        self.guard = guard or NewsGuard()

    def assess(self, symbol: str, now: datetime) -> LiveNewsResult:
        events = self.provider.events(now)
        status = getattr(self.provider, "status", NewsProviderStatus(True, type(self.provider).__name__, len(events), None, None))
        if not status.available:
            return LiveNewsResult(None, status, None, ["NEWS_DATA_UNAVAILABLE"])
        self.guard.set_events(events)
        assessment = self.guard.assess(symbol, now)
        return LiveNewsResult(assessment, status, assessment.clear_for_new_entry, list(assessment.reason_codes))
