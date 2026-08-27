from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any
from datetime import datetime as _datetime
from enum import Enum

from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.live_news import LiveNewsGuardService
from atlas.services.live_static_zones import LiveStaticZoneBuilder
from atlas.services.market_costs import MarketCostService
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.trading_calendar import TradingCalendar
from atlas.supervisor.runtime import SupervisorContext, SupervisorRuntime


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, _datetime):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple, list)):
        return [_primitive(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _primitive(v) for k, v in value.items()}
    if is_dataclass(value):
        return _primitive(asdict(value))
    return str(value)


@dataclass(slots=True)
class PaperReview:
    decision: str
    reason_codes: list[str]
    gates: dict[str, bool | None]
    entry: float | None
    stop: float | None
    target: float | None
    net_rr: float | None
    static_zone: dict[str, Any] | None
    news: dict[str, Any]
    market_costs: dict[str, Any]
    confluence_count: int = 1
    confluence_level: str = "SINGLE_SIGNAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LivePaperSupervisorPipeline:
    """Complete read-only Supervisor review for a Coordinator opportunity package."""

    def __init__(
        self,
        feed: MT5MarketDataFeed,
        news: LiveNewsGuardService | None,
        supervisor: SupervisorRuntime | None = None,
        zone_builder: LiveStaticZoneBuilder | None = None,
        costs: MarketCostService | None = None,
        calendar: TradingCalendar | None = None,
        market_limits_by_symbol: dict[str, dict[str, float]] | None = None,
        adaptive_spread_baseline_path: str | None = "runtime/adaptive_spread_baseline.json",
    ) -> None:
        self.feed = feed
        self.news = news
        self.supervisor = supervisor or SupervisorRuntime()
        self.zone_builder = zone_builder or LiveStaticZoneBuilder(feed)
        self.costs = costs or MarketCostService()
        self.calendar = calendar or TradingCalendar()
        self.market_limits_by_symbol = market_limits_by_symbol or {}
        self.adaptive_spread_baseline_path = adaptive_spread_baseline_path
        self._zones: dict[str, Any] = {}

    @staticmethod
    def _prices(pkg: dict[str, Any], direction: str) -> tuple[float | None, float | None, float | None]:
        t = pkg.get("primary_trigger") or {}
        entry = t.get("entry_reference")
        stop = t.get("final_stop")
        if entry is None or stop is None:
            return None, None, None
        entry, stop = float(entry), float(stop)
        risk = abs(entry - stop)
        if risk <= 0:
            return entry, stop, None
        target_r = float(pkg.get("target_r", 2.0) or 2.0)
        if target_r <= 0:
            return entry, stop, None
        target = entry + target_r * risk if direction == "LONG" else entry - target_r * risk
        return entry, stop, target

    def _zone_service(self, symbol: str, refresh: bool = False):
        if refresh or symbol not in self._zones:
            self._zones[symbol] = self.zone_builder.build(symbol)
        return self._zones[symbol]

    def review(self, *, symbol: str, direction: str, package: dict[str, Any], alignment_ok: bool, fib_ok: bool, proposed_risk_pct: float = 0.5, now: datetime | None = None) -> PaperReview:
        now = now or datetime.now(timezone.utc)
        entry, stop, target = self._prices(package, direction)
        m15_ok = package.get("coordination_state") == "READY_FOR_SUPERVISOR_REVIEW"
        fresh = package.get("freshness") == "VALID"
        structural_stop_ok = entry is not None and stop is not None and target is not None

        cal = self.calendar.assess(now)
        news_gate: bool | None = None
        news_info: dict[str, Any] = {"status": "NOT_CONFIGURED", "reason_codes": ["NEWS_DATA_UNAVAILABLE"]}
        if self.news is not None:
            nr = self.news.assess(symbol, now)
            news_gate = nr.gate
            news_info = {
                "provider": _primitive(nr.provider_status),
                "assessment": _primitive(nr.assessment) if nr.assessment else None,
                "reason_codes": nr.reason_codes,
            }

        zone_gate: bool | None = None
        zone_info = None
        spread_gate: bool | None = None
        net_rr_ok: bool | None = None
        net_rr = None
        cost_info: dict[str, Any] = {"status": "NOT_EVALUATED"}
        reasons = list(package.get("reason_codes", [])) + list(cal.reason_codes) + list(news_info.get("reason_codes", []))
        if structural_stop_ok:
            zsvc = self._zone_service(symbol)
            za = zsvc.assess_target_path(entry, target, direction)
            zone_gate = za.clear_for_target
            zone_info = {
                "clear_for_target": za.clear_for_target,
                "blocking_zone": _primitive(za.blocking_zone) if za.blocking_zone else None,
                "nearest_support": _primitive(za.nearest_support) if za.nearest_support else None,
                "nearest_resistance": _primitive(za.nearest_resistance) if za.nearest_resistance else None,
                "reason_codes": za.reason_codes,
            }
            reasons += za.reason_codes
            meta = self.feed.ensure_symbol(symbol)
            tick = self.feed.tick(symbol)
            point = meta.point if meta.point > 0 else 1.0
            spread_points = tick.spread_price / point
            limits = self.market_limits_by_symbol.get(symbol.upper())
            if limits is None:
                reasons.append("MARKET_COST_CALIBRATION_UNAVAILABLE")
                spread_gate = None
                net_rr_ok = None
                cost_info = {"status": "UNAVAILABLE", "spread_points": spread_points}
            else:
                max_spread = float(limits["max_spread_points"])
                reject_nonpositive = bool(limits.get("reject_nonpositive_spread", True))
                slippage_validated = bool(limits.get("slippage_validated", False))
                expected_slippage = float(limits.get("expected_slippage_points", 0.0))
                max_slippage = float(limits.get("max_slippage_points", 0.0))
                cost_basis = str(limits.get("cost_basis", "SPREAD_ONLY"))
                if reject_nonpositive and spread_points <= 0:
                    spread_gate = None
                    net_rr_ok = None
                    reasons.append("NONPOSITIVE_SPREAD_UNVERIFIED")
                    cost_info = {
                        "status": "WAIT_NONPOSITIVE_SPREAD",
                        "spread_points": spread_points,
                        "max_spread_points": max_spread,
                        "cost_basis": cost_basis,
                        "slippage_validated": slippage_validated,
                    }
                else:
                    adaptive_decision = None
                    adaptive_required = bool(limits.get("adaptive_spread_enabled", False))
                    if adaptive_required and self.adaptive_spread_baseline_path:
                        try:
                            guard = AdaptiveSpreadGuard.from_file(
                                self.adaptive_spread_baseline_path,
                                elevated_multiple=float(limits.get("adaptive_elevated_multiple", 1.5)),
                                block_multiple=float(limits.get("adaptive_block_multiple", 2.0)),
                                p95_block_multiple=float(limits.get("adaptive_p95_block_multiple", 1.5)),
                                max_spread_to_stop_ratio=float(limits.get("max_spread_to_stop_ratio", 0.25)),
                            )
                            stop_distance_points = abs(entry-stop)/point if point > 0 else None
                            adaptive_decision = guard.assess(symbol, spread_points, now=now, stop_distance_points=stop_distance_points)
                        except Exception:
                            adaptive_decision = None
                    if adaptive_required and adaptive_decision is None:
                        spread_gate = None
                        net_rr_ok = None
                        reasons.append("ADAPTIVE_SPREAD_BASELINE_UNAVAILABLE")
                        cost_info = {"status":"WAIT_ADAPTIVE_SPREAD_BASELINE","spread_points":spread_points}
                    elif adaptive_required and adaptive_decision.allowed is not True:
                        spread_gate = False if adaptive_decision.allowed is False else None
                        net_rr_ok = None
                        reasons += list(adaptive_decision.reasons)
                        cost_info = {"status":"ADAPTIVE_SPREAD_BLOCK" if adaptive_decision.allowed is False else "WAIT_ADAPTIVE_SPREAD",
                                     "spread_points":spread_points,"adaptive":adaptive_decision.to_dict()}
                    else:
                        if adaptive_required and adaptive_decision is not None:
                            reasons += list(adaptive_decision.reasons)
                        ca = self.costs.assess(entry=entry, stop=stop, target=target, point_size=point,
                                           spread_points=spread_points, expected_slippage_points=expected_slippage,
                                           max_spread_points=max_spread, max_slippage_points=max_slippage,
                                           min_net_rr=self.supervisor.policy.min_net_rr_after_costs)
                        # In PAPER_ONLY mode the spread gate is actionable for shadow decisions,
                        # while slippage remains explicitly unvalidated and cannot authorize execution.
                        spread_gate = ca.spread_ok if not slippage_validated else (ca.spread_ok and ca.slippage_ok)
                        net_rr_ok = ca.net_rr_ok
                        net_rr = ca.net_rr
                        reasons += ca.reason_codes
                        if not slippage_validated:
                            reasons.append("PAPER_COST_SPREAD_ONLY_SLIPPAGE_UNMEASURED")
                        cost_info = {
                            "status": "PAPER_SPREAD_ONLY" if not slippage_validated else "EXECUTION_COST_VALIDATED",
                            "spread_points": ca.spread_points,
                            "max_spread_points": max_spread,
                            "expected_slippage_points": ca.slippage_points,
                            "slippage_validated": slippage_validated,
                            "cost_basis": cost_basis,
                            "net_rr": ca.net_rr,
                            "adaptive": adaptive_decision.to_dict() if adaptive_decision is not None else None,
                        }

        confluence_count = int(package.get("confluence_count", 1) or 1)
        confluence_level = str(package.get("confluence_level", "SINGLE_SIGNAL"))
        if confluence_count >= 2:
            reasons.append("SUPERVISOR_RECEIVED_MULTI_AGENT_CONFLUENCE")

        ctx = SupervisorContext(
            symbol=symbol,
            proposed_risk_pct=proposed_risk_pct,
            day_ok=cal.new_entries_allowed,
            session_ok=cal.new_entries_allowed,
            alignment_ok=alignment_ok,
            fib_ok=fib_ok,
            m15_ok=m15_ok,
            freshness_ok=fresh,
            static_zone_ok=zone_gate,
            spread_ok=spread_gate,
            news_ok=news_gate,
            structural_stop_ok=structural_stop_ok,
            net_rr_ok=net_rr_ok,
            pattern_policy_resolved=True,
        )
        rr = self.supervisor.review(ctx)
        reasons += rr.reason_codes
        # Keep order while removing duplicates.
        dedup = list(dict.fromkeys(reasons))
        return PaperReview(rr.result.decision.value, dedup, rr.gates, entry, stop, target, net_rr, zone_info, news_info, cost_info, confluence_count, confluence_level)
