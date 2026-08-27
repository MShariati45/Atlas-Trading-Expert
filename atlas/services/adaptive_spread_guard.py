from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
from statistics import median
from typing import Iterable


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    f = pos - lo
    return xs[lo] * (1.0 - f) + xs[hi] * f


def classify_session(dt: datetime) -> str:
    """Simple UTC liquidity buckets used only for spread comparison.

    They are deliberately broad. Rollover gets its own bucket because spread
    behavior there should never teach Atlas that a temporary liquidity shock is
    normal for the rest of the trading day.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    h = dt.astimezone(timezone.utc).hour
    if 21 <= h < 23:
        return "ROLLOVER"
    if 23 <= h or h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "LONDON"
    if 13 <= h < 21:
        return "NEW_YORK"
    return "OTHER"


def _robust_positive(values: Iterable[float]) -> list[float]:
    xs = [float(v) for v in values if float(v) > 0]
    if len(xs) < 8:
        return xs
    med = median(xs)
    deviations = [abs(x - med) for x in xs]
    mad = median(deviations)
    if mad <= 0:
        # Percentile trim still protects the baseline from isolated shock prints.
        hi = _pct(xs, 0.99)
        return [x for x in xs if hi is None or x <= hi]
    robust_sigma = 1.4826 * mad
    ceiling = med + 6.0 * robust_sigma
    return [x for x in xs if x <= ceiling]


@dataclass(frozen=True, slots=True)
class SpreadBaseline:
    symbol: str
    session: str
    samples: int
    median_points: float
    p90_points: float
    p95_points: float
    source_samples: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AdaptiveSpreadDecision:
    symbol: str
    session: str
    status: str
    allowed: bool | None
    current_spread_points: float
    median_points: float | None
    p95_points: float | None
    elevated_threshold_points: float | None
    block_threshold_points: float | None
    spread_to_stop_ratio: float | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def build_baseline_from_csv(
    csv_path: str | Path,
    *,
    min_session_samples: int = 60,
    min_all_samples: int = 120,
    max_tick_age_seconds: float = 30.0,
) -> dict:
    """Build observation-only rolling spread baselines from broker samples.

    No trading limits are rewritten. Shock/outlier samples are excluded from the
    learned *normal* baseline, but remain in the raw CSV for audit/research.
    """
    by_symbol_session: dict[tuple[str, str], list[float]] = {}
    by_symbol_all: dict[str, list[float]] = {}
    source_counts: dict[tuple[str, str], int] = {}

    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            symbol = str(row.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            try:
                spread = float(row["spread_points"])
                age = float(row.get("tick_age_seconds", 0.0) or 0.0)
            except Exception:
                continue
            if spread <= 0 or age > max_tick_age_seconds:
                continue
            raw_time = row.get("utc_time") or row.get("time_utc")
            try:
                dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")) if raw_time else datetime.now(timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)
            session = classify_session(dt)
            key = (symbol, session)
            by_symbol_session.setdefault(key, []).append(spread)
            by_symbol_all.setdefault(symbol, []).append(spread)
            source_counts[key] = source_counts.get(key, 0) + 1

    symbols: dict[str, dict] = {}
    for symbol, all_values in by_symbol_all.items():
        robust_all = _robust_positive(all_values)
        all_row = None
        if len(robust_all) >= min_all_samples:
            all_row = SpreadBaseline(
                symbol=symbol,
                session="ALL",
                samples=len(robust_all),
                median_points=float(median(robust_all)),
                p90_points=float(_pct(robust_all, 0.90)),
                p95_points=float(_pct(robust_all, 0.95)),
                source_samples=len(all_values),
            ).to_dict()
        sessions = {}
        for (sym, session), vals in by_symbol_session.items():
            if sym != symbol:
                continue
            robust = _robust_positive(vals)
            if len(robust) < min_session_samples:
                continue
            sessions[session] = SpreadBaseline(
                symbol=symbol,
                session=session,
                samples=len(robust),
                median_points=float(median(robust)),
                p90_points=float(_pct(robust, 0.90)),
                p95_points=float(_pct(robust, 0.95)),
                source_samples=source_counts[(sym, session)],
            ).to_dict()
        symbols[symbol] = {"all": all_row, "sessions": sessions}

    return {
        "mode": "ADAPTIVE_SPREAD_BASELINE_OBSERVATION",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "rules": {
            "outlier_policy": "ROBUST_MAD_OR_P99_TRIM",
            "session_aware": True,
            "does_not_rewrite_policy": True,
        },
    }


class AdaptiveSpreadGuard:
    """Fail-closed symbol/session spread guard for Coordinator/Supervisor use."""

    def __init__(
        self,
        baseline: dict,
        *,
        elevated_multiple: float = 1.5,
        block_multiple: float = 2.0,
        p95_block_multiple: float = 1.5,
        max_spread_to_stop_ratio: float = 0.25,
        absolute_hard_cap_points: float | None = None,
    ) -> None:
        self.baseline = baseline
        self.elevated_multiple = float(elevated_multiple)
        self.block_multiple = float(block_multiple)
        self.p95_block_multiple = float(p95_block_multiple)
        self.max_spread_to_stop_ratio = float(max_spread_to_stop_ratio)
        self.absolute_hard_cap_points = None if absolute_hard_cap_points is None else float(absolute_hard_cap_points)

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "AdaptiveSpreadGuard":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), **kwargs)

    def assess(
        self,
        symbol: str,
        current_spread_points: float,
        *,
        now: datetime | None = None,
        stop_distance_points: float | None = None,
    ) -> AdaptiveSpreadDecision:
        symbol = symbol.upper()
        now = now or datetime.now(timezone.utc)
        session = classify_session(now)
        row = self.baseline.get("symbols", {}).get(symbol)
        if not isinstance(row, dict):
            return AdaptiveSpreadDecision(symbol, session, "UNAVAILABLE", None, current_spread_points, None, None, None, None, None, ("ADAPTIVE_SPREAD_BASELINE_MISSING",))
        base = row.get("sessions", {}).get(session) or row.get("all")
        if not isinstance(base, dict):
            return AdaptiveSpreadDecision(symbol, session, "UNAVAILABLE", None, current_spread_points, None, None, None, None, None, ("ADAPTIVE_SPREAD_BASELINE_INSUFFICIENT",))
        med = float(base["median_points"])
        p95 = float(base["p95_points"])
        elevated = max(p95, med * self.elevated_multiple)
        block = max(med * self.block_multiple, p95 * self.p95_block_multiple)
        if self.absolute_hard_cap_points is not None:
            block = min(block, self.absolute_hard_cap_points)

        reasons: list[str] = []
        ratio = None
        if current_spread_points <= 0:
            reasons.append("NONPOSITIVE_SPREAD_UNVERIFIED")
            return AdaptiveSpreadDecision(symbol, session, "UNAVAILABLE", None, current_spread_points, med, p95, elevated, block, ratio, tuple(reasons))

        if stop_distance_points is not None and stop_distance_points > 0:
            ratio = current_spread_points / stop_distance_points
            if ratio > self.max_spread_to_stop_ratio:
                reasons.append("SPREAD_TOO_LARGE_RELATIVE_TO_STRUCTURAL_STOP")

        if current_spread_points >= block:
            reasons.append("ABNORMAL_SPREAD_MULTIPLE_BLOCK")
            status = "BLOCK"
            allowed: bool | None = False
        elif current_spread_points > elevated:
            reasons.append("ELEVATED_SPREAD_CAUTION")
            status = "ELEVATED"
            allowed = True
        else:
            status = "NORMAL"
            allowed = True

        if "SPREAD_TOO_LARGE_RELATIVE_TO_STRUCTURAL_STOP" in reasons:
            status = "BLOCK"
            allowed = False
        return AdaptiveSpreadDecision(symbol, session, status, allowed, current_spread_points, med, p95, elevated, block, ratio, tuple(reasons))
