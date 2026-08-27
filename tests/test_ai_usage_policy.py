from datetime import datetime, timezone
from atlas.providers.usage_policy import AIUsageLedger, AIUsagePolicy


def test_ai_is_disabled_by_default():
    ok, reason = AIUsageLedger().can_call(AIUsagePolicy(), task="SUPERVISOR_ADVISORY")
    assert not ok and reason == "AI_DISABLED"


def test_ai_budget_and_cache_are_enforced():
    p = AIUsagePolicy(enabled=True, max_calls_per_day=1, max_calls_per_month=2, cache_ttl_seconds=3600)
    ledger = AIUsageLedger()
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    ok, _ = ledger.can_call(p, task="SUPERVISOR_ADVISORY", cache_key="event-1", now=now)
    assert ok
    ledger.commit(cache_key="event-1", now=now)
    ok, reason = ledger.can_call(p, task="SUPERVISOR_ADVISORY", cache_key="event-1", now=now)
    assert not ok and reason == "AI_CACHE_HIT"
    ok, reason = ledger.can_call(p, task="SUPERVISOR_ADVISORY", cache_key="event-2", now=now)
    assert not ok and reason == "AI_DAILY_CALL_CAP_REACHED"
