from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True)
class MarketCostAssessment:
    spread_ok: bool
    slippage_ok: bool
    net_rr_ok: bool
    spread_points: float
    slippage_points: float
    net_rr: float
    reason_codes: list[str]

class MarketCostService:
    """Symbol-aware spread/slippage gate with net executable R:R."""

    def assess(
        self,
        *,
        entry: float,
        stop: float,
        target: float,
        point_size: float,
        spread_points: float,
        expected_slippage_points: float,
        max_spread_points: float,
        max_slippage_points: float,
        min_net_rr: float | None = 2.0,
    ) -> MarketCostAssessment:
        if point_size <= 0:
            raise ValueError("point_size must be positive")
        risk_points = abs(entry - stop) / point_size
        reward_points = abs(target - entry) / point_size
        execution_cost = max(spread_points, 0.0) + max(expected_slippage_points, 0.0)
        effective_risk = risk_points + execution_cost
        effective_reward = max(reward_points - execution_cost, 0.0)
        net_rr = effective_reward / effective_risk if effective_risk > 0 else 0.0
        spread_ok = spread_points <= max_spread_points
        slippage_ok = expected_slippage_points <= max_slippage_points
        net_rr_ok = True if min_net_rr is None else (net_rr + 1e-12 >= min_net_rr)
        reasons: list[str] = []
        if not spread_ok:
            reasons.append("SPREAD_TOO_HIGH")
        if not slippage_ok:
            reasons.append("SLIPPAGE_TOO_HIGH")
        if not net_rr_ok:
            reasons.append("NET_RR_BELOW_MINIMUM")
        if not reasons:
            reasons.append("MARKET_COSTS_ACCEPTABLE")
        return MarketCostAssessment(spread_ok, slippage_ok, net_rr_ok, spread_points, expected_slippage_points, net_rr, reasons)
