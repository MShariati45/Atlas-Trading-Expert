from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from atlas.market_data.mt5_feed import Candle, MT5MarketDataFeed
from atlas.research.candlestick_challenger.engine import (
    RollingZoneEngine,
    atr,
    build_trade_candidate,
    counter_move_present,
    detect_patterns,
)


@dataclass(frozen=True, slots=True)
class CandlestickSetupRule:
    pattern: str
    zone_timeframe: str
    require_counter_move: bool
    target_r: float = 2.0
    research_note: str = ""


# Frozen from the v0.24.15 one-year broker-native S/R-independent study.
# These are deliberately selective; weak pattern/pair combinations are omitted.
DEFAULT_WHITELIST: dict[str, tuple[CandlestickSetupRule, ...]] = {
    "EURUSD": (
        CandlestickSetupRule("SHOOTING_STAR_PIN", "H4", True, 2.0, "40.00% WR, +0.200R/trade, 160 resolved"),
        CandlestickSetupRule("EVENING_STAR", "H4", True, 2.0, "38.19% WR, +0.146R/trade, 144 resolved"),
        CandlestickSetupRule("BEARISH_ENGULFING", "H4", False, 2.0, "37.55% WR, +0.127R/trade, 466 resolved"),
    ),
    "USDJPY": (
        CandlestickSetupRule("MORNING_STAR", "H1", True, 2.0, "46.99% WR, +0.410R/trade, 83 resolved"),
        CandlestickSetupRule("HAMMER_PIN", "H1", False, 2.0, "46.06% WR, +0.382R/trade, 165 resolved"),
        CandlestickSetupRule("BULLISH_ENGULFING", "H1", True, 2.0, "43.85% WR, +0.315R/trade, 130 resolved"),
        CandlestickSetupRule("MORNING_STAR", "H4", True, 2.0, "42.95% WR, +0.289R/trade, 149 resolved"),
    ),
    "USDCAD": (
        CandlestickSetupRule("SHOOTING_STAR_PIN", "D1", True, 2.0, "40.91% WR, +0.227R/trade, 132 resolved"),
        CandlestickSetupRule("MORNING_STAR", "H4", True, 2.0, "39.42% WR, +0.183R/trade, 104 resolved"),
        CandlestickSetupRule("EVENING_STAR", "D1", True, 2.0, "39.04% WR, +0.171R/trade, 146 resolved"),
    ),
    "XAUUSD": (
        CandlestickSetupRule("SHOOTING_STAR_PIN", "H4", False, 2.0, "43.08% WR, +0.292R/trade, 195 resolved"),
        CandlestickSetupRule("MORNING_STAR", "H1", True, 2.0, "40.24% WR, +0.207R/trade, 82 resolved"),
        CandlestickSetupRule("SHOOTING_STAR_PIN", "H1", True, 2.0, "40.17% WR, +0.205R/trade, 117 resolved"),
    ),
}


class M15CandlestickSRLiveAgent:
    """Selective live M15 candlestick-at-S/R specialist.

    The agent is independent of H4/H1 trend direction. It only emits a trigger
    when the latest completed M15 pattern matches a symbol-specific whitelist and
    reacts at the researched D1/H4/H1 support/resistance timeframe.
    """

    agent_id = "M15_CANDLESTICK_SR"

    def __init__(
        self,
        feed: MT5MarketDataFeed,
        whitelist: dict[str, tuple[CandlestickSetupRule, ...]] | None = None,
        enabled: bool = True,
    ) -> None:
        self.feed = feed
        self.whitelist = whitelist or DEFAULT_WHITELIST
        self.enabled = enabled
        self.zones = RollingZoneEngine()

    def rules_for(self, symbol: str, direction: str) -> tuple[CandlestickSetupRule, ...]:
        wanted = "LONG" if direction.upper() == "LONG" else "SHORT"
        out = []
        for rule in self.whitelist.get(symbol.upper(), ()): 
            if rule.pattern in {"HAMMER_PIN", "BULLISH_ENGULFING", "MORNING_STAR"} and wanted == "LONG":
                out.append(rule)
            elif rule.pattern in {"SHOOTING_STAR_PIN", "BEARISH_ENGULFING", "EVENING_STAR"} and wanted == "SHORT":
                out.append(rule)
        return tuple(out)

    def evaluate(self, symbol: str, direction: str, m15_bars: list[Candle]) -> dict[str, Any] | None:
        if not self.enabled or len(m15_bars) < 30:
            return None
        rules = self.rules_for(symbol, direction)
        if not rules:
            return None
        i = len(m15_bars) - 1
        current_atr = atr(m15_bars, 20)
        if current_atr <= 0:
            return None
        signals = [s for s in detect_patterns(m15_bars, i, current_atr) if s.direction == direction.upper()]
        if not signals:
            return None
        histories = {
            "D1": self.feed.closed_bars(symbol, "D1", 300),
            "H4": self.feed.closed_bars(symbol, "H4", 550),
            "H1": self.feed.closed_bars(symbol, "H1", 750),
        }
        point = self.feed.ensure_symbol(symbol).point
        cm = counter_move_present(m15_bars, i, direction.upper())

        candidates: list[tuple[float, dict[str, Any]]] = []
        for signal in signals:
            matching = [r for r in rules if r.pattern == signal.pattern and (not r.require_counter_move or cm)]
            if not matching:
                continue
            # Evaluate only the S/R timeframes approved for this exact setup.
            # Do not let a nearer/higher-priority unapproved timeframe mask an
            # approved H1/H4/D1 zone.
            desired_kind = "SUPPORT" if signal.direction == "LONG" else "RESISTANCE"
            pattern_price = signal.pattern_low if signal.direction == "LONG" else signal.pattern_high
            zone_options = []
            for rule in matching:
                tf = rule.zone_timeframe
                max_dist_atr = 0.55 if tf == "H1" else 0.70
                for kind, low, high, touches, strength in self.zones.build(tf, histories.get(tf, [])):
                    if kind != desired_kind:
                        continue
                    distance = 0.0 if low <= pattern_price <= high else min(abs(pattern_price-low), abs(pattern_price-high))
                    dist_atr = distance / max(current_atr, 1e-12)
                    if dist_atr <= max_dist_atr:
                        from atlas.research.candlestick_challenger.engine import ZoneHit
                        zone_options.append((strength - 0.10*dist_atr, rule, ZoneHit(tf, kind, low, high, (low+high)/2.0, touches, strength, dist_atr)))
            if not zone_options:
                continue
            _, rule, zone = max(zone_options, key=lambda x: x[0])
            # H4 assessment is intentionally neutral here; the live specialist is S/R independent.
            from atlas.research.candlestick_challenger.engine import DirectionAssessment
            neutral = DirectionAssessment("INDEPENDENT", 1.0, "CANDLESTICK_SR_INDEPENDENT", ())
            trade = build_trade_candidate(symbol, m15_bars, signal, neutral, zone, point, "EARLY", filter_name="LIVE_WHITELIST")
            if trade is None:
                continue
            score = signal.quality + zone.strength - 0.10 * zone.distance_atr
            data = {
                "pattern_type": signal.pattern,
                "direction": signal.direction,
                "entry_reference": trade.entry,
                "raw_stop_anchor": signal.pattern_low if signal.direction == "LONG" else signal.pattern_high,
                "applied_buffer": abs(trade.stop - (signal.pattern_low if signal.direction == "LONG" else signal.pattern_high)),
                "final_stop": trade.stop,
                "trigger_time": signal.end_time,
                "event_id": f"CANDLE_SR|{symbol.upper()}|{signal.pattern}|{zone.timeframe}|{signal.end_time}",
                "freshness": "VALID",
                "last_reason_code": "WHITELISTED_CANDLESTICK_AT_MAJOR_SR",
                "zone_timeframe": zone.timeframe,
                "zone_kind": zone.kind,
                "zone_low": zone.low,
                "zone_high": zone.high,
                "zone_strength": zone.strength,
                "zone_distance_atr": zone.distance_atr,
                "counter_move": cm,
                "counter_move_required": rule.require_counter_move,
                "quality": signal.quality,
                "target_r": rule.target_r,
                "research_note": rule.research_note,
            }
            candidates.append((score, data))
        if not candidates:
            return None
        _, best = max(candidates, key=lambda x: x[0])
        return {
            "agent_id": self.agent_id,
            "status": "VALID_TRIGGER",
            "data": best,
            "reason_codes": [best["last_reason_code"]],
        }

    def configuration(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "whitelist": {k: [asdict(r) for r in v] for k, v in self.whitelist.items()},
        }
