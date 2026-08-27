from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable

from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.market_data.mt5_feed import Candle, MT5MarketDataFeed
from atlas.services.static_zones import StaticZone, StaticZoneService, ZoneState


@dataclass(slots=True)
class ZoneBuildConfig:
    lookback_d1: int = 500
    lookback_h4: int = 900
    min_touches: int = 3
    atr_period: int = 20
    cluster_atr_fraction: float = 0.30
    min_width_points: float = 5.0


class LiveStaticZoneBuilder:
    """Derive cacheable D1/H4 horizontal zones from completed candles only.

    The detector uses confirmed swing reactions, clusters nearby reaction prices,
    and builds an area from the reaction bodies/wicks rather than an exact line.
    It is deterministic and does not call an LLM.
    """

    def __init__(self, feed: MT5MarketDataFeed, config: ZoneBuildConfig | None = None) -> None:
        self.feed = feed
        self.config = config or ZoneBuildConfig()
        self.swing = HistoricalStructureBootstrapper(left=2, right=2, min_swings=4)

    @staticmethod
    def _atr(bars: list[Candle], period: int) -> float:
        recent = bars[-period:] if len(bars) >= period else bars
        if not recent:
            return 0.0
        trs: list[float] = []
        prev = None
        for b in recent:
            tr = b.high - b.low if prev is None else max(b.high - b.low, abs(b.high - prev), abs(b.low - prev))
            trs.append(tr)
            prev = b.close
        return mean(trs) if trs else 0.0

    def _build_timeframe(self, symbol: str, timeframe: str, count: int) -> list[StaticZone]:
        bars = self.feed.closed_bars(symbol, timeframe, count)
        if len(bars) < 30:
            return []
        swings = self.swing.swings(bars)
        if len(swings) < self.config.min_touches:
            return []
        meta = self.feed.ensure_symbol(symbol)
        atr = max(self._atr(bars, self.config.atr_period), meta.point * self.config.min_width_points)
        tolerance = max(atr * self.config.cluster_atr_fraction, meta.point * self.config.min_width_points)

        clusters: list[list] = []
        for s in swings:
            placed = False
            for c in clusters:
                center = mean(x.price for x in c)
                if abs(s.price - center) <= tolerance:
                    c.append(s)
                    placed = True
                    break
            if not placed:
                clusters.append([s])

        zones: list[StaticZone] = []
        for c in clusters:
            if len(c) < self.config.min_touches:
                continue
            idxs = [x.index for x in c]
            reaction_bars = [bars[i] for i in idxs if 0 <= i < len(bars)]
            if not reaction_bars:
                continue
            # Area construction: include the meaningful body edge and reaction wick extremes.
            lows = []
            highs = []
            for b in reaction_bars:
                body_low = min(b.open, b.close)
                body_high = max(b.open, b.close)
                lows.append(min(b.low, body_low))
                highs.append(max(b.high, body_high))
            low = min(lows)
            high = max(highs)
            # Avoid zones expanding unreasonably due to one abnormal candle.
            center = mean(x.price for x in c)
            max_half = tolerance * 1.5
            low = max(low, center - max_half)
            high = min(high, center + max_half)
            if high <= low:
                low, high = center - tolerance / 2, center + tolerance / 2

            ages = [len(bars) - 1 - i for i in idxs]
            freshness = 1.0 / (1.0 + mean(ages) / 100.0)
            touch_score = min(1.0, len(c) / 6.0)
            tf_weight = 1.0 if timeframe == "D1" else 0.8
            strength = round(min(1.0, 0.45 * touch_score + 0.35 * freshness + 0.20 * tf_weight), 4)
            zones.append(StaticZone(
                timeframe=timeframe,
                low=low,
                high=high,
                strength=strength,
                touch_count=len(c),
                state=ZoneState.ACTIVE,
                label=f"{timeframe}_REACTION_CLUSTER",
            ))
        return sorted(zones, key=lambda z: (z.low + z.high) / 2.0)

    def build(self, symbol: str) -> StaticZoneService:
        zones = self._build_timeframe(symbol, "D1", self.config.lookback_d1)
        zones += self._build_timeframe(symbol, "H4", self.config.lookback_h4)
        return StaticZoneService(zones)
