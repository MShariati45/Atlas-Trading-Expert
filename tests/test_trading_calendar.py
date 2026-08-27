from datetime import datetime
from zoneinfo import ZoneInfo
from atlas.services.trading_calendar import TradingCalendar

TZ = ZoneInfo("America/Vancouver")

def test_thursday_entries_allowed():
    a = TradingCalendar().assess(datetime(2026, 8, 20, 12, tzinfo=TZ))
    assert a.new_entries_allowed

def test_friday_entries_blocked_and_flat_window():
    cal = TradingCalendar(friday_flat_hour=13)
    a = cal.assess(datetime(2026, 8, 21, 14, tzinfo=TZ))
    assert not a.new_entries_allowed
    assert a.force_flat

def test_sunday_after_market_open_allowed():
    a = TradingCalendar(sunday_open_hour=14).assess(datetime(2026, 8, 23, 15, tzinfo=TZ))
    assert a.new_entries_allowed
