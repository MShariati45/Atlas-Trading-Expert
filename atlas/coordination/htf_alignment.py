from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class HTFAlignmentReport:
    symbol: str
    h4_formal_trend: str
    h4_effective_direction: str
    h1_trend: str
    aligned: bool
    direction: str
    state: str
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HTFAlignmentService:
    """Downstream comparison only; never writes into H4 or H1 state."""

    def evaluate(self, symbol: str, h4: dict[str, Any], h1: dict[str, Any]) -> HTFAlignmentReport:
        h4_formal = str(h4.get("trend", "UNINITIALIZED")).upper()
        h4_effective = str(h4.get("effective_direction") or h4_formal).upper()
        h4_phase = str(h4.get("phase", "UNINITIALIZED")).upper()
        h1_trend = str(h1.get("trend", "UNINITIALIZED")).upper()
        h1_phase = str(h1.get("phase", "UNINITIALIZED")).upper()
        valid = {"BULLISH", "BEARISH"}
        if h4_effective not in valid or h1_trend not in valid:
            return HTFAlignmentReport(symbol, h4_formal, h4_effective, h1_trend, False, "NONE", "WAIT", "HTF_STRUCTURE_UNRESOLVED")

        # A formal H1 trend label is deliberately retained while an opposite
        # reversal candidate develops. Downstream services must not mistake that
        # historical label for current alignment permission. Ordinary H1
        # corrections remain eligible because they are the context Fibonacci is
        # designed to measure.
        if "REVERSAL" in h1_phase:
            return HTFAlignmentReport(symbol, h4_formal, h4_effective, h1_trend, False, "NONE", "WAIT", "H1_REVERSAL_STATE_UNRESOLVED")

        # H4 also preserves its formal trend during transition. If no separately
        # confirmed early/effective direction has replaced the formal direction,
        # the coordinator must wait rather than trade from stale H4 permission.
        # If a confirmed H4 early direction exists, it may be compared downstream
        # without rewriting H4's formal trend.
        if "REVERSAL" in h4_phase and h4_effective == h4_formal:
            return HTFAlignmentReport(symbol, h4_formal, h4_effective, h1_trend, False, "NONE", "WAIT", "H4_REVERSAL_STATE_UNRESOLVED")

        if h4_effective == h1_trend:
            reason = "ALIGNED_WITH_H4_EARLY_DIRECTION" if h4_effective != h4_formal else "ALIGNED_WITH_H4_FORMAL_TREND"
            return HTFAlignmentReport(symbol, h4_formal, h4_effective, h1_trend, True, h1_trend, f"ALIGNED_{h1_trend}", reason)
        return HTFAlignmentReport(symbol, h4_formal, h4_effective, h1_trend, False, "NONE", "NOT_ALIGNED", "H4_H1_INDEPENDENT_REPORTS_MISMATCH")
