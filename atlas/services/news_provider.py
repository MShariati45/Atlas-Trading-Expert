from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Protocol

from atlas.services.news_guard import NewsEvent
from atlas.services.news_mapping import symbols_for_currencies


class ScheduledNewsProvider(Protocol):
    def events(self, now_utc: datetime | None = None) -> list[NewsEvent]: ...


@dataclass(slots=True)
class NewsProviderStatus:
    available: bool
    provider: str
    event_count: int
    last_refresh_utc: str | None
    error: str | None = None
    source_generated_at_utc: str | None = None
    valid_until_utc: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    covered_currencies: tuple[str, ...] = ()
    missing_required_currencies: tuple[str, ...] = ()
    coverage_ok: bool = True


class JsonScheduledNewsProvider:
    """Strict provider-neutral scheduled-news adapter.

    Production-ready payloads are dictionaries with:
      generated_at_utc, valid_until_utc, source_name, source_url,
      coverage_currencies, events.

    Events may name affected_symbols directly or provide currencies, which Atlas
    maps to its canonical four-symbol watchlist. Strict coverage prevents a
    partial calendar from being treated as comprehensive.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        strict_freshness: bool = False,
        min_validity_seconds: int = 0,
        strict_provenance: bool = False,
        required_currencies: set[str] | frozenset[str] | None = None,
        required_event_families: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.path = Path(path)
        self.strict_freshness = bool(strict_freshness)
        self.min_validity_seconds = int(min_validity_seconds)
        self.strict_provenance = bool(strict_provenance)
        self.required_currencies = frozenset(str(x).upper() for x in (required_currencies or set()))
        self.required_event_families = frozenset(str(x) for x in (required_event_families or set()))
        self.status = NewsProviderStatus(False, "JSON", 0, None, "NOT_REFRESHED")

    @staticmethod
    def _dt(value: str) -> datetime:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def events(self, now_utc: datetime | None = None) -> list[NewsEvent]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            generated = raw.get("generated_at_utc") if isinstance(raw, dict) else None
            valid_until = raw.get("valid_until_utc") if isinstance(raw, dict) else None
            source_name = raw.get("source_name") if isinstance(raw, dict) else None
            source_url = raw.get("source_url") if isinstance(raw, dict) else None
            coverage = tuple(sorted({str(x).upper() for x in (raw.get("coverage_currencies", []) if isinstance(raw, dict) else [])}))
            missing = tuple(sorted(self.required_currencies - set(coverage)))
            family_map = raw.get("required_event_families", {}) if isinstance(raw, dict) else {}
            missing_families = tuple(sorted(name for name in self.required_event_families if family_map.get(name) is not True))

            if self.strict_freshness:
                now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
                if not generated or not valid_until:
                    raise ValueError("LIVE_NEWS_METADATA_REQUIRED")
                valid_dt = self._dt(str(valid_until))
                if (valid_dt - now).total_seconds() < self.min_validity_seconds:
                    raise ValueError("LIVE_NEWS_SCHEDULE_STALE_OR_TOO_SHORT")
            if self.strict_provenance:
                if not source_name or not source_url:
                    raise ValueError("LIVE_NEWS_PROVENANCE_REQUIRED")
                if not coverage:
                    raise ValueError("LIVE_NEWS_COVERAGE_METADATA_REQUIRED")
            if missing:
                raise ValueError("LIVE_NEWS_COVERAGE_MISSING_" + "_".join(missing))
            if missing_families:
                raise ValueError("LIVE_NEWS_EVENT_FAMILIES_MISSING_" + "_".join(missing_families))
            if self.required_event_families and raw.get("coverage_status") != "FULL_PRIMARY_BACKBONE":
                raise ValueError("LIVE_NEWS_COVERAGE_STATUS_NOT_FULL")

            rows = raw.get("events", []) if isinstance(raw, dict) else raw
            out: list[NewsEvent] = []
            for r in rows:
                currencies = frozenset(str(x).upper() for x in r.get("currencies", []))
                explicit_symbols = frozenset(str(x).upper() for x in r.get("affected_symbols", []))
                affected = explicit_symbols or symbols_for_currencies(currencies)
                out.append(NewsEvent(
                    event_id=str(r["event_id"]),
                    starts_at_utc=self._dt(str(r["starts_at_utc"])),
                    affected_symbols=affected,
                    impact=str(r.get("impact", "HIGH")),
                    title=str(r.get("title", "")),
                    currencies=currencies,
                    source_name=str(r.get("source_name", source_name or "")),
                    source_url=str(r.get("source_url", source_url or "")),
                    blackout_before_minutes=int(r["blackout_before_minutes"]) if r.get("blackout_before_minutes") is not None else None,
                    blackout_after_minutes=int(r.get("blackout_after_minutes", 0)),
                    open_trade_review_minutes=int(r["open_trade_review_minutes"]) if r.get("open_trade_review_minutes") is not None else None,
                ))
            self.status = NewsProviderStatus(
                True, "JSON", len(out), datetime.now(timezone.utc).isoformat(), None,
                str(generated) if generated else None,
                str(valid_until) if valid_until else None,
                str(source_name) if source_name else None,
                str(source_url) if source_url else None,
                coverage, missing, not missing,
            )
            return out
        except Exception as exc:
            self.status = NewsProviderStatus(False, "JSON", 0, datetime.now(timezone.utc).isoformat(), str(exc), coverage_ok=False)
            return []
