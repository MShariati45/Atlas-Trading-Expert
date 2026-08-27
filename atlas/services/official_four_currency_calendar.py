from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import re
from zoneinfo import ZoneInfo

from atlas.services.official_calendar import OfficialCalendarEvent


def _local(year:int, month:int, day:int, hour:int, minute:int, zone:str) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)


def _ev(prefix:str, dt:datetime, title:str, currency:str, source_name:str, source_url:str) -> OfficialCalendarEvent:
    return OfficialCalendarEvent(
        event_id=f"{prefix}:{dt.date().isoformat()}:{re.sub(r'[^A-Za-z0-9]+','-',title).strip('-')[:48]}",
        starts_at_utc=dt,
        title=title,
        currencies=frozenset({currency}),
        impact="HIGH",
        source_name=source_name,
        source_url=source_url,
    )

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ECB_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
BOC_URL = "https://www.bankofcanada.ca/press/upcoming-events/"
STATCAN_URL = "https://www150.statcan.gc.ca/n1/dai-quo/cal2-eng.htm"
STATCAN_RELEASE_PDF_URL = "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
BOJ_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/"
JP_LFS_URL = "https://www.stat.go.jp/english/data/roudou/1543.htm"
JP_CPI_URL = "https://www.stat.go.jp/english/data/cpi/"


def official_policy_events_2026() -> list[OfficialCalendarEvent]:
    """Primary-source policy dates/times for the remainder of 2026.

    Fed statement times are 14:00 America/New_York. ECB decisions are 14:15
    Europe/Berlin. Bank of Canada decisions are 09:45 America/Toronto.
    BoJ decision time is not fixed; noon Tokyo is a nominal anchor and the payload
    carries a wide event-specific blackout window in the composite runner.
    """
    out: list[OfficialCalendarEvent] = []
    for m,d in [(9,16),(10,28),(12,9)]:
        out.append(_ev("FED", _local(2026,m,d,14,0,"America/New_York"), "FOMC policy decision", "USD", "Federal Reserve", FED_URL))
    for m,d in [(9,10),(10,29),(12,17)]:
        out.append(_ev("ECB", _local(2026,m,d,14,15,"Europe/Berlin"), "ECB monetary policy decisions", "EUR", "European Central Bank", ECB_URL))
    for m,d in [(9,2),(10,28),(12,9)]:
        out.append(_ev("BOC", _local(2026,m,d,9,45,"America/Toronto"), "Bank of Canada interest rate announcement", "CAD", "Bank of Canada", BOC_URL))
    for m,d in [(9,18),(10,30),(12,18)]:
        out.append(_ev("BOJ", _local(2026,m,d,12,0,"Asia/Tokyo"), "Bank of Japan monetary policy decision window", "JPY", "Bank of Japan", BOJ_URL))
    return sorted(out, key=lambda e:e.starts_at_utc)


def japan_macro_events_2026() -> list[OfficialCalendarEvent]:
    out: list[OfficialCalendarEvent] = []
    # Official Labour Force Survey release schedule, basic tabulation, 08:30 JST.
    for m,d,ref in [(8,28,"July"),(10,2,"August"),(10,30,"September"),(12,1,"October"),(12,25,"November")]:
        out.append(_ev("JP-LFS", _local(2026,m,d,8,30,"Asia/Tokyo"), f"Japan Labour Force Survey ({ref} 2026)", "JPY", "Statistics Bureau of Japan", JP_LFS_URL))
    # CPI rule: preceding-month Japan CPI is released 08:30 JST on Friday of the week including the 19th.
    for m,d,ref in [(8,21,"July"),(9,18,"August"),(10,23,"September"),(11,20,"October"),(12,18,"November")]:
        out.append(_ev("JP-CPI", _local(2026,m,d,8,30,"Asia/Tokyo"), f"Japan Consumer Price Index ({ref} 2026)", "JPY", "Statistics Bureau of Japan", JP_CPI_URL))
    return sorted(out, key=lambda e:e.starts_at_utc)


def canada_macro_events_2026() -> list[OfficialCalendarEvent]:
    """Official Statistics Canada CPI/LFS release dates for the remainder of 2026.

    Dates are maintained from Statistics Canada's 2026-2027 major economic
    release schedule. Releases are anchored at 08:30 America/Toronto, the
    standard Daily release time for these series.
    """
    out: list[OfficialCalendarEvent] = []
    # Labour Force Survey: August-November 2026 reference periods.
    for m,d,ref in [(9,4,"August"),(10,9,"September"),(11,6,"October"),(12,4,"November")]:
        out.append(_ev("STATCAN-LFS", _local(2026,m,d,8,30,"America/Toronto"),
                       f"Canada Labour Force Survey ({ref} 2026)", "CAD",
                       "Statistics Canada", STATCAN_RELEASE_PDF_URL))
    # Consumer Price Index: August-November 2026 reference periods.
    for m,d,ref in [(9,14,"August"),(10,19,"September"),(11,16,"October"),(12,14,"November")]:
        out.append(_ev("STATCAN-CPI", _local(2026,m,d,8,30,"America/Toronto"),
                       f"Canada Consumer Price Index ({ref} 2026)", "CAD",
                       "Statistics Canada", STATCAN_RELEASE_PDF_URL))
    return sorted(out, key=lambda e:e.starts_at_utc)


def required_family_coverage(events: list[OfficialCalendarEvent]) -> dict[str, bool]:
    """Return required scheduled-event family coverage for the Atlas watchlist."""
    ids=[e.event_id for e in events]
    titles=[e.title.lower() for e in events]
    return {
        "USD_FOMC": any(i.startswith("FED:") for i in ids),
        "USD_EMPLOYMENT": any("employment situation" in t for t in titles),
        "USD_CPI": any(i.startswith("BLS:") and "consumer price index" in t for i,t in zip(ids,titles)),
        "EUR_ECB": any(i.startswith("ECB:") for i in ids),
        "CAD_BOC": any(i.startswith("BOC:") for i in ids),
        "CAD_CPI": any(i.startswith("STATCAN-CPI:") for i in ids),
        "CAD_LFS": any(i.startswith("STATCAN-LFS:") for i in ids),
        "JPY_BOJ": any(i.startswith("BOJ:") for i in ids),
        "JPY_CPI": any(i.startswith("JP-CPI:") for i in ids),
        "JPY_LFS": any(i.startswith("JP-LFS:") for i in ids),
    }


def validate_source_markers(text: str, markers: tuple[str,...]) -> bool:
    low = unescape(re.sub(r"<[^>]+>", " ", text)).lower()
    return all(m.lower() in low for m in markers)


def parse_statcan_high_impact_schedule(html: str, *, now_year: int = 2026) -> list[OfficialCalendarEvent]:
    """Best-effort parser for Statistics Canada's rolling official release schedule.

    Only CPI and Labour Force Survey are promoted to HIGH. The Daily publishes at
    08:30 Eastern unless an item-specific official time supersedes it.
    """
    text = unescape(re.sub(r"<[^>]+>", "\n", html))
    text = re.sub(r"[\t\r ]+", " ", text)
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    month = None; day = None
    months = {n:i for i,n in enumerate(("January","February","March","April","May","June","July","August","September","October","November","December"),1)}
    out: list[OfficialCalendarEvent] = []
    for line in lines:
        md = re.fullmatch(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})", line)
        if md:
            month, day = months[md.group(1)], int(md.group(2)); continue
        if month and day:
            low=line.lower()
            if "consumer price index" in low:
                out.append(_ev("STATCAN-CPI", _local(now_year,month,day,8,30,"America/Toronto"), line, "CAD", "Statistics Canada", STATCAN_URL))
            elif "labour force survey" in low:
                out.append(_ev("STATCAN-LFS", _local(now_year,month,day,8,30,"America/Toronto"), line, "CAD", "Statistics Canada", STATCAN_URL))
    # dedupe by date/title
    uniq={ (e.starts_at_utc,e.title):e for e in out }
    return sorted(uniq.values(), key=lambda e:e.starts_at_utc)
