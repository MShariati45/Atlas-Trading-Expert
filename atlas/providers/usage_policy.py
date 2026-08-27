from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class AIUsagePolicy:
    """Hard budget guard for optional AI advisory calls.

    Atlas core trading logic is deterministic. AI is optional and may only be
    used for event-driven advisory/review work after local logic has produced a
    meaningful event. The default policy is fully disabled, so demo observation
    cannot consume paid AI API calls by accident.
    """

    enabled: bool = False
    event_driven_only: bool = True
    max_calls_per_day: int = 8
    max_calls_per_month: int = 120
    cache_ttl_seconds: int = 86400
    allowed_tasks: frozenset[str] = frozenset({
        "SUPERVISOR_ADVISORY",
        "POST_TRADE_REVIEW",
        "OFF_HOURS_RESEARCH",
    })

    def __post_init__(self) -> None:
        if self.max_calls_per_day < 0 or self.max_calls_per_month < 0:
            raise ValueError("AI call caps cannot be negative")
        if self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds cannot be negative")


@dataclass(slots=True)
class AIUsageLedger:
    day_key: str = ""
    month_key: str = ""
    day_calls: int = 0
    month_calls: int = 0
    cache: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def _keys(now: datetime) -> tuple[str, str]:
        utc = now.astimezone(timezone.utc)
        return utc.date().isoformat(), f"{utc.year:04d}-{utc.month:02d}"

    def _roll(self, now: datetime) -> None:
        day, month = self._keys(now)
        if self.month_key != month:
            self.month_key = month
            self.month_calls = 0
            self.cache.clear()
        if self.day_key != day:
            self.day_key = day
            self.day_calls = 0

    def can_call(self, policy: AIUsagePolicy, *, task: str, cache_key: str | None = None, now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        self._roll(now)
        if not policy.enabled:
            return False, "AI_DISABLED"
        if task not in policy.allowed_tasks:
            return False, "AI_TASK_NOT_ALLOWED"
        if cache_key:
            ts = self.cache.get(cache_key)
            if ts is not None and now.timestamp() - ts <= policy.cache_ttl_seconds:
                return False, "AI_CACHE_HIT"
        if self.day_calls >= policy.max_calls_per_day:
            return False, "AI_DAILY_CALL_CAP_REACHED"
        if self.month_calls >= policy.max_calls_per_month:
            return False, "AI_MONTHLY_CALL_CAP_REACHED"
        return True, "AI_CALL_ALLOWED"

    def commit(self, *, cache_key: str | None = None, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._roll(now)
        self.day_calls += 1
        self.month_calls += 1
        if cache_key:
            self.cache[cache_key] = now.timestamp()
