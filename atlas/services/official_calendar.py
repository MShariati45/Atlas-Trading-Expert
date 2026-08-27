from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

from atlas.services.news_mapping import symbols_for_currencies


@dataclass(slots=True, frozen=True)
class OfficialCalendarEvent:
    event_id: str
    starts_at_utc: datetime
    title: str
    currencies: frozenset[str]
    impact: str
    source_name: str
    source_url: str

    def to_payload(self) -> dict:
        return {
            "event_id": self.event_id,
            "starts_at_utc": self.starts_at_utc.isoformat(),
            "title": self.title,
            "currencies": sorted(self.currencies),
            "affected_symbols": sorted(symbols_for_currencies(self.currencies)),
            "impact": self.impact,
            "source_name": self.source_name,
            "source_url": self.source_url,
        }


_BLS_HIGH = (
    "employment situation",
    "consumer price index",
    "producer price index",
    "employment cost index",
)


def classify_bls_impact(title: str) -> str:
    low = title.lower()
    return "HIGH" if any(k in low for k in _BLS_HIGH) else "MEDIUM"


def _unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def parse_bls_ics(text: str, *, source_url: str) -> list[OfficialCalendarEvent]:
    """Parse the official BLS ICS without external dependencies.

    BLS calendar times are America/New_York. Date-only holiday events are ignored.
    """
    lines = _unfold_ics(text)
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = []
        elif line == "END:VEVENT" and cur is not None:
            blocks.append(cur)
            cur = None
        elif cur is not None:
            cur.append(line)

    out: list[OfficialCalendarEvent] = []
    ny = ZoneInfo("America/New_York")
    for block in blocks:
        props: dict[str, str] = {}
        for line in block:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            props[key] = value
        summary = next((v for k, v in props.items() if k.startswith("SUMMARY")), "").replace("\\,", ",").strip()
        uid = next((v for k, v in props.items() if k.startswith("UID")), summary)
        dt_key = next((k for k in props if k.startswith("DTSTART")), None)
        if not dt_key or not summary:
            continue
        raw = props[dt_key].strip()
        # Ignore all-day/date-only entries such as federal holidays.
        if re.fullmatch(r"\d{8}", raw):
            continue
        dt: datetime
        if raw.endswith("Z"):
            dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            fmt = "%Y%m%dT%H%M%S" if len(raw) >= 15 else "%Y%m%dT%H%M"
            dt = datetime.strptime(raw, fmt).replace(tzinfo=ny).astimezone(timezone.utc)
        out.append(OfficialCalendarEvent(
            event_id="BLS:" + uid,
            starts_at_utc=dt,
            title=summary,
            currencies=frozenset({"USD"}),
            impact=classify_bls_impact(summary),
            source_name="U.S. Bureau of Labor Statistics",
            source_url=source_url,
        ))
    return sorted(out, key=lambda x: x.starts_at_utc)
