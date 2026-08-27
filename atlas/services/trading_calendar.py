from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

@dataclass(slots=True)
class TradingWindowAssessment:
    new_entries_allowed: bool
    force_flat: bool
    reason_codes: list[str]

class TradingCalendar:
    """Atlas week governance in the owner's Vancouver timezone.

    New entries are allowed from Sunday market-open onward through Thursday.
    Friday is management-only and all positions must be flat before market close.
    Exact broker close handling is delegated to the execution bridge/scheduler.
    """

    def __init__(self, timezone_name: str = "America/Vancouver", sunday_open_hour: int = 14, friday_flat_hour: int = 13) -> None:
        self.tz = ZoneInfo(timezone_name)
        self.sunday_open_hour = sunday_open_hour
        self.friday_flat_hour = friday_flat_hour

    def assess(self, when: datetime) -> TradingWindowAssessment:
        local = when.astimezone(self.tz)
        weekday = local.weekday()  # Mon=0, Sun=6
        if weekday in {0, 1, 2, 3}:
            return TradingWindowAssessment(True, False, ["TRADING_WINDOW_OPEN"])
        if weekday == 4:
            force_flat = local.hour >= self.friday_flat_hour
            codes = ["FRIDAY_NEW_ENTRIES_BLOCKED"]
            if force_flat:
                codes.append("FRIDAY_FORCE_FLAT_WINDOW")
            return TradingWindowAssessment(False, force_flat, codes)
        if weekday == 6 and local.hour >= self.sunday_open_hour:
            return TradingWindowAssessment(True, False, ["SUNDAY_MARKET_WINDOW_OPEN"])
        return TradingWindowAssessment(False, False, ["WEEKEND_LOCKED"])
