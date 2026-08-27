from __future__ import annotations

from dataclasses import dataclass

from .profile import (
    AtlasStrategyProfile,
    HTF_ANY,
    HTF_H4_ALIGNED_H1_ANY,
    HTF_H4_ALIGNED_H1_OPPOSED,
    HTF_H4_H1_ALIGNED,
    HTF_H4_H1_OPPOSED,
)


@dataclass(frozen=True, slots=True)
class PatternGateDecision:
    allowed: bool
    reason_code: str
    target_r: float


class PatternPolicyGate:
    """Symbol/pattern-specific HTF gate from audited Atlas research.

    H1 is no longer a universal confirmation gate. It remains available as
    context where the measured pattern/symbol population benefited from an
    aligned or corrective/opposed H1 state.
    """

    def __init__(self, profile: AtlasStrategyProfile) -> None:
        self.profile = profile

    @staticmethod
    def _bias(direction: str) -> str | None:
        return {"LONG": "BULLISH", "SHORT": "BEARISH"}.get(str(direction).upper())

    def evaluate(self, *, symbol: str, pattern: str, direction: str, h4_trend: str | None, h1_trend: str | None) -> PatternGateDecision:
        rule = self.profile.pattern_rule(symbol, pattern)
        if not rule.enabled:
            return PatternGateDecision(False, "PATTERN_DISABLED_FOR_SYMBOL", rule.target_r)
        requested = self._bias(direction)
        if requested is None:
            return PatternGateDecision(False, "INVALID_DIRECTION", rule.target_r)
        h4 = str(h4_trend or "UNAVAILABLE").upper()
        h1 = str(h1_trend or "UNAVAILABLE").upper()
        if h4 not in {"BULLISH", "BEARISH"}:
            return PatternGateDecision(False, "H4_DIRECTION_UNAVAILABLE", rule.target_r)
        if rule.htf_mode != HTF_H4_ALIGNED_H1_ANY and h1 not in {"BULLISH", "BEARISH"}:
            return PatternGateDecision(False, "H1_DIRECTION_UNAVAILABLE", rule.target_r)
        h4_aligned = h4 == requested
        h1_aligned = h1 == requested

        allowed = False
        if rule.htf_mode == HTF_ANY:
            allowed = True
        elif rule.htf_mode == HTF_H4_ALIGNED_H1_ANY:
            allowed = h4_aligned
        elif rule.htf_mode == HTF_H4_ALIGNED_H1_OPPOSED:
            allowed = h4_aligned and not h1_aligned
        elif rule.htf_mode == HTF_H4_H1_ALIGNED:
            allowed = h4_aligned and h1_aligned
        elif rule.htf_mode == HTF_H4_H1_OPPOSED:
            allowed = (not h4_aligned) and (not h1_aligned)
        return PatternGateDecision(
            allowed,
            "PATTERN_HTF_POLICY_MATCH" if allowed else "PATTERN_HTF_POLICY_MISMATCH",
            rule.target_r,
        )
