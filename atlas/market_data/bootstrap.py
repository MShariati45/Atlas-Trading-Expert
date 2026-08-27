from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

from atlas.agents.h4_structure import PricePoint
from atlas.market_data.mt5_feed import Candle


@dataclass(slots=True, frozen=True)
class SwingPoint:
    kind: str  # HIGH | LOW
    price: float
    time: datetime
    index: int


@dataclass(slots=True, frozen=True)
class BootstrapResult:
    trend: str
    origin: PricePoint
    endpoint: PricePoint
    control_pivot: PricePoint
    confidence: float
    reason_code: str
    swings_used: int
    bars_used: int

    def to_dict(self):
        return asdict(self)


class HistoricalStructureBootstrapper:
    """Deterministic initial-state discovery from completed candles only.

    This bootstrapper does not replace Atlas's incremental strategic engine.
    It is used only when no persisted state exists. It finds confirmed local
    swings, compresses same-type pivots, and derives the latest coherent HH/HL
    or LH/LL sequence. Once seeded, normal processing is incremental.
    """

    def __init__(self, left: int = 2, right: int = 2, min_swings: int = 4) -> None:
        if left < 1 or right < 1:
            raise ValueError("left/right must be >= 1")
        self.left = left
        self.right = right
        self.min_swings = min_swings

    def swings(self, candles: Iterable[Candle]) -> list[SwingPoint]:
        bars = list(candles)
        out: list[SwingPoint] = []
        for i in range(self.left, len(bars) - self.right):
            c = bars[i]
            left = bars[i-self.left:i]
            right = bars[i+1:i+1+self.right]
            is_high = c.high > max(x.high for x in left) and c.high >= max(x.high for x in right)
            is_low = c.low < min(x.low for x in left) and c.low <= min(x.low for x in right)
            if is_high:
                out.append(SwingPoint("HIGH", c.high, c.time_utc, i))
            if is_low:
                out.append(SwingPoint("LOW", c.low, c.time_utc, i))
        out.sort(key=lambda x: (x.index, 0 if x.kind == "LOW" else 1))
        return self._compress(out)

    @staticmethod
    def _compress(swings: list[SwingPoint]) -> list[SwingPoint]:
        if not swings:
            return []
        result = [swings[0]]
        for s in swings[1:]:
            prev = result[-1]
            if s.kind != prev.kind:
                result.append(s)
                continue
            if s.kind == "HIGH" and s.price >= prev.price:
                result[-1] = s
            elif s.kind == "LOW" and s.price <= prev.price:
                result[-1] = s
        return result

    @staticmethod
    def _pp(s: SwingPoint) -> PricePoint:
        return PricePoint(float(s.price), s.time.isoformat())


    @staticmethod
    def trendline_anchors(swings: list[SwingPoint], trend: str, max_anchors: int = 3) -> list[SwingPoint]:
        """Return recent validated pivots suitable for the H4 diagonal structure component.

        Bearish structure uses descending swing highs; bullish structure uses
        ascending swing lows. Two anchors are sufficient; a third qualifying
        pivot strengthens confidence. This helper selects pivots only -- the
        H4 trendline engine remains responsible for breakout/confirmation.
        """
        kind = "HIGH" if trend == "BEARISH" else "LOW"
        pts = [s for s in swings if s.kind == kind]
        if len(pts) < 2:
            return []
        selected=[]
        newest=pts[-1]
        selected=[newest]
        for older in reversed(pts[:-1]):
            valid = older.price > selected[0].price if trend == "BEARISH" else older.price < selected[0].price
            if valid:
                selected.insert(0, older)
                if len(selected) >= max_anchors:
                    break
        return selected if len(selected) >= 2 else []

    def derive(self, candles: Iterable[Candle]) -> BootstrapResult:
        bars = list(candles)
        swings = self.swings(bars)
        if len(swings) < self.min_swings:
            raise ValueError("INSUFFICIENT_CONFIRMED_SWINGS")

        # Work backwards for the latest four alternating pivots that form a
        # coherent two-swing trend structure. This is deliberately stricter
        # than comparing first/last candle closes.
        for end in range(len(swings), 3, -1):
            a, b, c, d = swings[end-4:end]
            kinds = [x.kind for x in (a, b, c, d)]
            if kinds == ["LOW", "HIGH", "LOW", "HIGH"]:
                if c.price > a.price and d.price > b.price:
                    return BootstrapResult(
                        trend="BULLISH",
                        origin=self._pp(c),
                        endpoint=self._pp(d),
                        control_pivot=self._pp(c),
                        confidence=0.90,
                        reason_code="BOOTSTRAP_BULLISH_HH_HL",
                        swings_used=len(swings),
                        bars_used=len(bars),
                    )
            if kinds == ["HIGH", "LOW", "HIGH", "LOW"]:
                if c.price < a.price and d.price < b.price:
                    return BootstrapResult(
                        trend="BEARISH",
                        origin=self._pp(c),
                        endpoint=self._pp(d),
                        control_pivot=self._pp(c),
                        confidence=0.90,
                        reason_code="BOOTSTRAP_BEARISH_LH_LL",
                        swings_used=len(swings),
                        bars_used=len(bars),
                    )

        raise ValueError("NO_COHERENT_RECENT_STRATEGIC_SEQUENCE")
