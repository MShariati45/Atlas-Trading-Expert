from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from statistics import mean
from typing import Iterable

from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.market_data.mt5_feed import Candle


@dataclass(slots=True, frozen=True)
class DirectionAssessment:
    state: str  # BULLISH | BEARISH | RANGE | TRANSITION
    confidence: float
    reason: str
    recent_swings: tuple[tuple[str, float, str], ...]


@dataclass(slots=True, frozen=True)
class ZoneHit:
    timeframe: str
    kind: str  # SUPPORT | RESISTANCE
    low: float
    high: float
    center: float
    touches: int
    strength: float
    distance_atr: float


@dataclass(slots=True, frozen=True)
class PatternSignal:
    pattern: str
    direction: str  # LONG | SHORT
    start_index: int
    end_index: int
    start_time: str
    end_time: str
    pattern_low: float
    pattern_high: float
    quality: float


@dataclass(slots=True)
class TradeCandidate:
    symbol: str
    signal_time: str
    pattern: str
    direction: str
    h4_state: str
    h4_confidence: float
    zone_timeframe: str
    zone_kind: str
    zone_low: float
    zone_high: float
    zone_strength: float
    counter_move: bool
    entry_model: str
    entry_time: str
    entry: float
    stop: float
    risk: float
    atr: float
    pattern_low: float
    pattern_high: float
    confirmation_time: str = ""
    filter_name: str = "ZONE_PATTERN"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Outcome:
    target_r: float
    outcome: str  # WIN | LOSS | UNRESOLVED
    realized_r: float | None
    exit_time: str
    exit_price: float | None
    bars_held: int
    mfe_r: float
    mae_r: float

    def to_dict(self) -> dict:
        return asdict(self)


def atr(bars: list[Candle], period: int = 20) -> float:
    if not bars:
        return 0.0
    recent = bars[-period:] if len(bars) >= period else bars
    trs: list[float] = []
    prev_close: float | None = None
    for b in recent:
        if prev_close is None:
            tr = b.high - b.low
        else:
            tr = max(b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close))
        trs.append(max(0.0, tr))
        prev_close = b.close
    return mean(trs) if trs else 0.0


class RecentImpulseDirectionEngine:
    """Simple H4 direction classifier based on the recent 2-3 meaningful swing legs.

    This intentionally does not attempt exact strategic-pivot reconstruction. Its job
    is only to answer the trading question: bullish, bearish, range, or transition.
    """

    def __init__(self, left: int = 2, right: int = 2, lookback_bars: int = 180) -> None:
        self.swing = HistoricalStructureBootstrapper(left=left, right=right, min_swings=4)
        self.lookback_bars = lookback_bars

    def classify(self, bars: list[Candle]) -> DirectionAssessment:
        sample = bars[-self.lookback_bars :]
        if len(sample) < 30:
            return DirectionAssessment("RANGE", 0.2, "INSUFFICIENT_H4_CONTEXT", ())
        swings = self.swing.swings(sample)
        if len(swings) < 4:
            return DirectionAssessment("RANGE", 0.3, "INSUFFICIENT_MEANINGFUL_SWINGS", ())
        recent = swings[-8:]
        highs = [s for s in recent if s.kind == "HIGH"][-3:]
        lows = [s for s in recent if s.kind == "LOW"][-3:]
        if len(highs) < 2 or len(lows) < 2:
            return DirectionAssessment("RANGE", 0.35, "INCOMPLETE_RECENT_SWING_PAIR", tuple((s.kind, s.price, s.time.isoformat()) for s in recent))

        high_up = highs[-1].price > highs[-2].price
        high_down = highs[-1].price < highs[-2].price
        low_up = lows[-1].price > lows[-2].price
        low_down = lows[-1].price < lows[-2].price

        # A third same-type swing strengthens persistence but is not required.
        bull_persist = len(highs) >= 3 and highs[-1].price > highs[-2].price > highs[-3].price
        bull_low_persist = len(lows) >= 3 and lows[-1].price > lows[-2].price > lows[-3].price
        bear_persist = len(highs) >= 3 and highs[-1].price < highs[-2].price < highs[-3].price
        bear_low_persist = len(lows) >= 3 and lows[-1].price < lows[-2].price < lows[-3].price

        if high_up and low_up:
            conf = 0.78 + (0.08 if bull_persist else 0.0) + (0.08 if bull_low_persist else 0.0)
            return DirectionAssessment("BULLISH", min(0.94, conf), "RECENT_HH_HL_PROGRESS", tuple((s.kind, s.price, s.time.isoformat()) for s in recent))
        if high_down and low_down:
            conf = 0.78 + (0.08 if bear_persist else 0.0) + (0.08 if bear_low_persist else 0.0)
            return DirectionAssessment("BEARISH", min(0.94, conf), "RECENT_LH_LL_PROGRESS", tuple((s.kind, s.price, s.time.isoformat()) for s in recent))

        # Mixed recent pivots: distinguish a material break from ordinary overlap.
        latest = recent[-1]
        previous_highs = [s.price for s in recent[:-1] if s.kind == "HIGH"]
        previous_lows = [s.price for s in recent[:-1] if s.kind == "LOW"]
        if latest.kind == "LOW" and previous_lows and latest.price < min(previous_lows[-2:]):
            return DirectionAssessment("TRANSITION", 0.62, "MIXED_STRUCTURE_WITH_NEW_LOWER_EXTREME", tuple((s.kind, s.price, s.time.isoformat()) for s in recent))
        if latest.kind == "HIGH" and previous_highs and latest.price > max(previous_highs[-2:]):
            return DirectionAssessment("TRANSITION", 0.62, "MIXED_STRUCTURE_WITH_NEW_HIGHER_EXTREME", tuple((s.kind, s.price, s.time.isoformat()) for s in recent))
        return DirectionAssessment("RANGE", 0.68, "RECENT_SWINGS_OVERLAP_OR_ALTERNATE", tuple((s.kind, s.price, s.time.isoformat()) for s in recent))


class RollingZoneEngine:
    """Build no-lookahead D1/H4/H1 support/resistance reaction zones."""

    LOOKBACK = {"D1": 260, "H4": 500, "H1": 700}
    MIN_TOUCHES = {"D1": 2, "H4": 2, "H1": 3}
    TF_WEIGHT = {"D1": 1.0, "H4": 0.9, "H1": 0.75}

    def __init__(self) -> None:
        self.swing = HistoricalStructureBootstrapper(left=2, right=2, min_swings=4)

    def build(self, timeframe: str, bars: list[Candle]) -> list[tuple[str, float, float, int, float]]:
        sample = bars[-self.LOOKBACK[timeframe] :]
        if len(sample) < 30:
            return []
        swings = self.swing.swings(sample)
        if not swings:
            return []
        a = max(atr(sample, 20), 1e-12)
        tolerance = a * (0.36 if timeframe == "H1" else 0.32)
        by_kind: dict[str, list] = {"LOW": [], "HIGH": []}
        for s in swings:
            by_kind[s.kind].append(s)
        out: list[tuple[str, float, float, int, float]] = []
        for kind, points in by_kind.items():
            clusters: list[list] = []
            for s in points:
                placed = False
                for cluster in clusters:
                    center = mean(x.price for x in cluster)
                    if abs(s.price - center) <= tolerance:
                        cluster.append(s)
                        placed = True
                        break
                if not placed:
                    clusters.append([s])
            for cluster in clusters:
                if len(cluster) < self.MIN_TOUCHES[timeframe]:
                    continue
                center = mean(x.price for x in cluster)
                half = tolerance * 0.65
                ages = [len(sample) - 1 - x.index for x in cluster]
                freshness = 1.0 / (1.0 + mean(ages) / 120.0)
                touch_score = min(1.0, len(cluster) / 5.0)
                strength = min(1.0, 0.45 * touch_score + 0.30 * freshness + 0.25 * self.TF_WEIGHT[timeframe])
                out.append(("SUPPORT" if kind == "LOW" else "RESISTANCE", center - half, center + half, len(cluster), strength))
        return out

    def nearest_hit(
        self,
        direction: str,
        pattern_low: float,
        pattern_high: float,
        m15_atr: float,
        histories: dict[str, list[Candle]],
    ) -> ZoneHit | None:
        desired = "SUPPORT" if direction == "LONG" else "RESISTANCE"
        pattern_price = pattern_low if direction == "LONG" else pattern_high
        hits: list[ZoneHit] = []
        for tf in ("D1", "H4", "H1"):
            for kind, low, high, touches, strength in self.build(tf, histories.get(tf, [])):
                if kind != desired:
                    continue
                distance = 0.0 if low <= pattern_price <= high else min(abs(pattern_price - low), abs(pattern_price - high))
                # H1 is allowed to be slightly tighter than higher timeframes.
                max_dist_atr = 0.55 if tf == "H1" else 0.70
                dist_atr = distance / max(m15_atr, 1e-12)
                if dist_atr <= max_dist_atr:
                    hits.append(ZoneHit(tf, kind, low, high, (low + high) / 2.0, touches, strength, dist_atr))
        if not hits:
            return None
        # Prefer higher timeframe, stronger and closer zones.
        order = {"D1": 3, "H4": 2, "H1": 1}
        return max(hits, key=lambda h: (order[h.timeframe], h.strength, -h.distance_atr))


def _candle_parts(b: Candle) -> tuple[float, float, float, float]:
    rng = max(b.high - b.low, 1e-12)
    body = abs(b.close - b.open)
    upper = b.high - max(b.open, b.close)
    lower = min(b.open, b.close) - b.low
    return rng, body, upper, lower


def detect_patterns(bars: list[Candle], i: int, current_atr: float) -> list[PatternSignal]:
    out: list[PatternSignal] = []
    if i < 0 or i >= len(bars):
        return out
    b = bars[i]
    rng, body, upper, lower = _candle_parts(b)
    body_floor = max(current_atr * 0.08, rng * 0.08)

    # Hammer / bullish pin bar.
    if body >= body_floor and lower >= max(2.0 * body, 0.45 * rng) and upper <= 0.35 * rng and b.close >= b.low + 0.60 * rng:
        q = min(1.0, 0.55 + 0.25 * min(2.0, lower / max(body, 1e-12)) / 2.0 + 0.20 * ((b.close - b.low) / rng))
        out.append(PatternSignal("HAMMER_PIN", "LONG", i, i, b.time_utc.isoformat(), b.time_utc.isoformat(), b.low, b.high, q))
    # Shooting star / bearish pin bar.
    if body >= body_floor and upper >= max(2.0 * body, 0.45 * rng) and lower <= 0.35 * rng and b.close <= b.low + 0.40 * rng:
        q = min(1.0, 0.55 + 0.25 * min(2.0, upper / max(body, 1e-12)) / 2.0 + 0.20 * ((b.high - b.close) / rng))
        out.append(PatternSignal("SHOOTING_STAR_PIN", "SHORT", i, i, b.time_utc.isoformat(), b.time_utc.isoformat(), b.low, b.high, q))

    if i >= 1:
        p = bars[i - 1]
        prev_body = abs(p.close - p.open)
        # Bullish engulfing: real body engulfs previous real body.
        if p.close < p.open and b.close > b.open and b.open <= p.close and b.close >= p.open and body >= max(prev_body * 0.95, current_atr * 0.16):
            q = min(1.0, 0.65 + 0.20 * min(1.5, body / max(prev_body, 1e-12)) / 1.5 + 0.15 * min(1.0, body / max(current_atr, 1e-12)))
            out.append(PatternSignal("BULLISH_ENGULFING", "LONG", i - 1, i, p.time_utc.isoformat(), b.time_utc.isoformat(), min(p.low, b.low), max(p.high, b.high), q))
        if p.close > p.open and b.close < b.open and b.open >= p.close and b.close <= p.open and body >= max(prev_body * 0.95, current_atr * 0.16):
            q = min(1.0, 0.65 + 0.20 * min(1.5, body / max(prev_body, 1e-12)) / 1.5 + 0.15 * min(1.0, body / max(current_atr, 1e-12)))
            out.append(PatternSignal("BEARISH_ENGULFING", "SHORT", i - 1, i, p.time_utc.isoformat(), b.time_utc.isoformat(), min(p.low, b.low), max(p.high, b.high), q))

    if i >= 2:
        a, m, c = bars[i - 2], bars[i - 1], bars[i]
        a_body = abs(a.close - a.open); m_body = abs(m.close - m.open); c_body = abs(c.close - c.open)
        # FX-friendly star definitions: no gap requirement, because spot FX gaps are uncommon intraday.
        if a.close < a.open and a_body >= current_atr * 0.22 and m_body <= a_body * 0.55 and c.close > c.open and c_body >= current_atr * 0.18 and c.close >= (a.open + a.close) / 2:
            q = min(1.0, 0.68 + 0.16 * min(1.0, a_body / max(current_atr, 1e-12)) + 0.16 * min(1.0, c_body / max(current_atr, 1e-12)))
            out.append(PatternSignal("MORNING_STAR", "LONG", i - 2, i, a.time_utc.isoformat(), c.time_utc.isoformat(), min(a.low, m.low, c.low), max(a.high, m.high, c.high), q))
        if a.close > a.open and a_body >= current_atr * 0.22 and m_body <= a_body * 0.55 and c.close < c.open and c_body >= current_atr * 0.18 and c.close <= (a.open + a.close) / 2:
            q = min(1.0, 0.68 + 0.16 * min(1.0, a_body / max(current_atr, 1e-12)) + 0.16 * min(1.0, c_body / max(current_atr, 1e-12)))
            out.append(PatternSignal("EVENING_STAR", "SHORT", i - 2, i, a.time_utc.isoformat(), c.time_utc.isoformat(), min(a.low, m.low, c.low), max(a.high, m.high, c.high), q))
    return out


def counter_move_present(bars: list[Candle], end_index: int, direction: str, lookback: int = 8) -> bool:
    start = max(0, end_index - lookback + 1)
    sample = bars[start : end_index + 1]
    if len(sample) < 4:
        return False
    first = mean(b.close for b in sample[:2])
    last = mean(b.close for b in sample[-2:])
    if direction == "LONG":
        return last < first
    return last > first


def find_choch_confirmation(bars: list[Candle], signal: PatternSignal, max_wait_bars: int = 4, internal_lookback: int = 5) -> int | None:
    prior_start = max(0, signal.start_index - internal_lookback)
    prior = bars[prior_start : signal.start_index]
    if not prior:
        return None
    if signal.direction == "LONG":
        level = max(b.high for b in prior)
        for j in range(signal.end_index + 1, min(len(bars), signal.end_index + 1 + max_wait_bars)):
            if bars[j].close > level:
                return j
    else:
        level = min(b.low for b in prior)
        for j in range(signal.end_index + 1, min(len(bars), signal.end_index + 1 + max_wait_bars)):
            if bars[j].close < level:
                return j
    return None


def build_trade_candidate(
    symbol: str,
    bars: list[Candle],
    signal: PatternSignal,
    direction: DirectionAssessment,
    zone: ZoneHit,
    point: float,
    entry_model: str,
    confirmation_index: int | None = None,
    filter_name: str = "ZONE_PATTERN",
) -> TradeCandidate | None:
    i = confirmation_index if entry_model == "CONFIRMED" else signal.end_index
    if i is None or i >= len(bars):
        return None
    current_atr = atr(bars[: i + 1], 20)
    if current_atr <= 0:
        return None
    entry = bars[i].close
    lookback = bars[max(0, signal.start_index - 8) : signal.end_index + 1]
    if signal.direction == "LONG":
        structural = min([signal.pattern_low] + [b.low for b in lookback])
    else:
        structural = max([signal.pattern_high] + [b.high for b in lookback])
    spread_price = max(0.0, bars[i].spread_points * point)
    buffer = max(spread_price * 1.5, current_atr * 0.10, point * 3)
    stop = structural - buffer if signal.direction == "LONG" else structural + buffer
    risk = entry - stop if signal.direction == "LONG" else stop - entry
    if risk <= max(point * 3, 1e-12) or not isfinite(risk):
        return None
    return TradeCandidate(
        symbol=symbol,
        signal_time=signal.end_time,
        pattern=signal.pattern,
        direction=signal.direction,
        h4_state=direction.state,
        h4_confidence=direction.confidence,
        zone_timeframe=zone.timeframe,
        zone_kind=zone.kind,
        zone_low=zone.low,
        zone_high=zone.high,
        zone_strength=zone.strength,
        counter_move=counter_move_present(bars, signal.end_index, signal.direction),
        entry_model=entry_model,
        entry_time=bars[i].time_utc.isoformat(),
        entry=entry,
        stop=stop,
        risk=risk,
        atr=current_atr,
        pattern_low=signal.pattern_low,
        pattern_high=signal.pattern_high,
        confirmation_time=bars[i].time_utc.isoformat() if entry_model == "CONFIRMED" else "",
        filter_name=filter_name,
    )


def evaluate_outcome(bars: list[Candle], entry_index: int, trade: TradeCandidate, target_r: float, max_hold_bars: int = 160) -> Outcome:
    target = trade.entry + trade.risk * target_r if trade.direction == "LONG" else trade.entry - trade.risk * target_r
    mfe = 0.0; mae = 0.0
    stop = trade.stop
    end = min(len(bars), entry_index + 1 + max_hold_bars)
    for held, j in enumerate(range(entry_index + 1, end), start=1):
        b = bars[j]
        if trade.direction == "LONG":
            favorable = (b.high - trade.entry) / trade.risk
            adverse = (trade.entry - b.low) / trade.risk
            hit_stop = b.low <= stop
            hit_target = b.high >= target
        else:
            favorable = (trade.entry - b.low) / trade.risk
            adverse = (b.high - trade.entry) / trade.risk
            hit_stop = b.high >= stop
            hit_target = b.low <= target
        mfe = max(mfe, favorable); mae = max(mae, adverse)
        # Conservative same-bar ambiguity: stop is assumed first.
        if hit_stop:
            return Outcome(target_r, "LOSS", -1.0, b.time_utc.isoformat(), stop, held, mfe, mae)
        if hit_target:
            return Outcome(target_r, "WIN", float(target_r), b.time_utc.isoformat(), target, held, mfe, mae)
    return Outcome(target_r, "UNRESOLVED", None, "", None, max(0, end - entry_index - 1), mfe, mae)
