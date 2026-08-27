from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


@dataclass(slots=True, frozen=True)
class SpreadSummary:
    samples: int
    zero_spread_samples: int
    minimum: float | None
    p50: float | None
    p90: float | None
    p95: float | None
    p99: float | None
    maximum: float | None
    slippage_status: str = "NOT_MEASURABLE_READ_ONLY"

    def to_dict(self) -> dict[str, object]:
        return {
            "samples": self.samples,
            "zero_spread_samples": self.zero_spread_samples,
            "min_spread_points": self.minimum,
            "p50_spread_points": self.p50,
            "p90_spread_points": self.p90,
            "p95_spread_points": self.p95,
            "p99_spread_points": self.p99,
            "max_spread_points": self.maximum,
            "slippage_status": self.slippage_status,
            "calibration_status": "OBSERVATION_ONLY_NOT_ACTIVE_LIMITS",
        }


def summarize_spreads(values: Iterable[float]) -> SpreadSummary:
    xs = [max(0.0, float(x)) for x in values]
    return SpreadSummary(
        samples=len(xs),
        zero_spread_samples=sum(1 for x in xs if x == 0.0),
        minimum=min(xs) if xs else None,
        p50=median(xs) if xs else None,
        p90=percentile(xs, 0.90),
        p95=percentile(xs, 0.95),
        p99=percentile(xs, 0.99),
        maximum=max(xs) if xs else None,
    )
