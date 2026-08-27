from datetime import datetime, timedelta, timezone
from atlas.services.news_guard import NewsEvent, NewsGuard

def test_high_impact_event_blocks_new_entry_inside_blackout():
    now = datetime(2026, 8, 18, 16, tzinfo=timezone.utc)
    guard = NewsGuard(pre_entry_blackout_minutes=30, open_trade_review_minutes=60)
    guard.set_events([NewsEvent("n1", now + timedelta(minutes=20), frozenset({"EURUSD"}))])
    a = guard.assess("EURUSD", now)
    assert not a.clear_for_new_entry
    assert a.force_review_open_trade

def test_irrelevant_symbol_is_clear():
    now = datetime(2026, 8, 18, 16, tzinfo=timezone.utc)
    guard = NewsGuard()
    guard.set_events([NewsEvent("n1", now + timedelta(minutes=10), frozenset({"USDJPY"}))])
    assert guard.assess("EURUSD", now).clear_for_new_entry


def test_default_high_impact_blackout_covers_90_minutes():
    from datetime import datetime, timedelta, timezone
    from atlas.services.news_guard import NewsEvent, NewsGuard
    now=datetime.now(timezone.utc)
    g=NewsGuard()
    g.set_events([NewsEvent('N90', now+timedelta(minutes=90), frozenset({'EURUSD'}), 'HIGH', 'major')])
    r=g.assess('EURUSD', now)
    assert r.clear_for_new_entry is False
    assert 'NEWS_BLACKOUT_ACTIVE' in r.reason_codes
