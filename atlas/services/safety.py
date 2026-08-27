from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from atlas.supervisor.runtime import SupervisorContext
from atlas.risk.policy import RiskPolicy
from .market_costs import MarketCostService
from .news_guard import NewsGuard
from .static_zones import StaticZoneService
from .trading_calendar import TradingCalendar

@dataclass(slots=True)
class SafetyInputs:
    symbol: str
    direction: str
    entry: float
    stop: float
    target: float
    point_size: float
    spread_points: float
    expected_slippage_points: float
    max_spread_points: float
    max_slippage_points: float
    proposed_risk_pct: float
    alignment_ok: bool | None
    fib_ok: bool | None
    m15_ok: bool | None
    freshness_ok: bool | None
    structural_stop_ok: bool | None
    now: datetime

class LiveSafetyService:
    """Builds live Supervisor gates from independent safety services."""

    def __init__(
        self,
        *,
        zones: StaticZoneService | None = None,
        news: NewsGuard | None = None,
        costs: MarketCostService | None = None,
        calendar: TradingCalendar | None = None,
        policy: RiskPolicy | None = None,
    ) -> None:
        self.zones = zones or StaticZoneService()
        self.news = news or NewsGuard()
        self.costs = costs or MarketCostService()
        self.calendar = calendar or TradingCalendar()
        self.policy = policy or RiskPolicy()

    def build_context(self, x: SafetyInputs) -> tuple[SupervisorContext, list[str]]:
        cal = self.calendar.assess(x.now)
        zone = self.zones.assess_target_path(x.entry, x.target, x.direction)
        news = self.news.assess(x.symbol, x.now)
        costs = self.costs.assess(
            entry=x.entry,
            stop=x.stop,
            target=x.target,
            point_size=x.point_size,
            spread_points=x.spread_points,
            expected_slippage_points=x.expected_slippage_points,
            max_spread_points=x.max_spread_points,
            max_slippage_points=x.max_slippage_points,
            min_net_rr=self.policy.min_net_rr_after_costs,
        )
        ctx = SupervisorContext(
            symbol=x.symbol,
            proposed_risk_pct=x.proposed_risk_pct,
            day_ok=cal.new_entries_allowed,
            session_ok=cal.new_entries_allowed,
            alignment_ok=x.alignment_ok,
            fib_ok=x.fib_ok,
            m15_ok=x.m15_ok,
            freshness_ok=x.freshness_ok,
            static_zone_ok=zone.clear_for_target,
            spread_ok=costs.spread_ok and costs.slippage_ok,
            news_ok=news.clear_for_new_entry,
            structural_stop_ok=x.structural_stop_ok,
            net_rr_ok=costs.net_rr_ok,
        )
        reasons = cal.reason_codes + zone.reason_codes + news.reason_codes + costs.reason_codes
        return ctx, reasons
