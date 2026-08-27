from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.agents.fibonacci import FibonacciRetracementEngine
from atlas.agents.h1_structure import H1StructureAgent, H1StructureState
from atlas.agents.h4_structure import H4StructureAgent, H4StructureState, TrendlineAnchor
from atlas.core.events import Event
from atlas.core.sqlite_state_store import SQLiteStateStore
from atlas.coordination.htf_alignment import HTFAlignmentService
from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.market_data.mt5_feed import Candle, MT5MarketDataFeed


def candle_payload(c: Candle) -> dict[str, Any]:
    return {
        "time": c.time_utc.isoformat(),
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "tick_volume": c.tick_volume,
        "spread_points": c.spread_points,
        "real_volume": c.real_volume,
    }


@dataclass(slots=True)
class RuntimeSnapshot:
    symbol: str
    h4: dict[str, Any]
    h1: dict[str, Any]
    fibonacci: dict[str, Any] | None
    last_h4_bar: str | None
    last_h1_bar: str | None
    alignment: dict[str, Any] | None = None


class ReadOnlyAtlasRuntime:
    """Persisted read-only runtime for MT5 demo observation.

    On first use it bootstraps H4/H1 from completed history. Thereafter it only
    processes bars newer than the persisted cursor. No order execution exists
    in this class.
    """

    def __init__(self, feed: MT5MarketDataFeed, state_path: str | Path) -> None:
        self.feed = feed
        self.store = SQLiteStateStore(state_path)
        self.h4 = H4StructureAgent(self.store)
        self.h1 = H1StructureAgent(self.store)
        self.bootstrapper = HistoricalStructureBootstrapper()
        self.fib = FibonacciRetracementEngine()
        self.alignment = HTFAlignmentService()

    def _cursor_key(self, symbol: str, timeframe: str) -> str:
        return f"cursor:{timeframe}:{symbol}"

    def _bootstrap_if_needed(self, symbol: str, history_count: int = 600) -> None:
        h4_key = self.h4._key(symbol)
        if self.store.get(h4_key) is None:
            bars = self.feed.closed_bars(symbol, "H4", history_count)
            result = self.bootstrapper.derive(bars)
            self.h4.seed(symbol, trend=result.trend, origin=result.origin, endpoint=result.endpoint, control_pivot=result.control_pivot)
            swings = self.bootstrapper.swings(bars)
            anchors = self.bootstrapper.trendline_anchors(swings, result.trend)
            if len(anchors) >= 2:
                self.h4.configure_trendline(symbol, [
                    TrendlineAnchor(price=float(a.price), time=a.time.isoformat(), kind=a.kind) for a in anchors
                ])
            self.store.set(self._cursor_key(symbol, "H4"), bars[-1].time_utc.isoformat())
            bootstrap_payload = result.to_dict()
            bootstrap_payload["trendline_anchor_count"] = len(anchors)
            bootstrap_payload["trendline_anchors"] = [
                {"price": float(a.price), "time": a.time.isoformat(), "kind": a.kind} for a in anchors
            ]
            self.store.set(f"bootstrap:H4:{symbol}", bootstrap_payload)

        h1_key = self.h1._key(symbol)
        if self.store.get(h1_key) is None:
            bars = self.feed.closed_bars(symbol, "H1", history_count)
            result = self.bootstrapper.derive(bars)
            self.h1.seed(symbol, trend=result.trend, origin=result.origin, endpoint=result.endpoint, control_pivot=result.control_pivot)
            self.store.set(self._cursor_key(symbol, "H1"), bars[-1].time_utc.isoformat())
            self.store.set(f"bootstrap:H1:{symbol}", result.to_dict())

    def _new_bars(self, symbol: str, timeframe: str, count: int = 20) -> list[Candle]:
        bars = self.feed.closed_bars(symbol, timeframe, count)
        cursor = self.store.get(self._cursor_key(symbol, timeframe))
        if cursor is None:
            return bars
        return [b for b in bars if b.time_utc.isoformat() > cursor]

    def poll_symbol(self, symbol: str) -> RuntimeSnapshot:
        self._bootstrap_if_needed(symbol)

        for bar in self._new_bars(symbol, "H4"):
            self.h4.handle(Event("H4_BAR_CLOSED", symbol=symbol, timeframe="H4", payload=candle_payload(bar)))
            self.store.set(self._cursor_key(symbol, "H4"), bar.time_utc.isoformat())

        for bar in self._new_bars(symbol, "H1"):
            payload = candle_payload(bar)
            self.h1.handle(Event("H1_BAR_CLOSED", symbol=symbol, timeframe="H1", payload=payload))
            self.store.set(self._cursor_key(symbol, "H1"), bar.time_utc.isoformat())

        h4_state = H4StructureState.from_dict(self.store.get(self.h4._key(symbol)))
        h1_state = H1StructureState.from_dict(self.store.get(self.h1._key(symbol)))
        alignment_report = self.alignment.evaluate(symbol, h4_state.to_dict(), h1_state.to_dict())
        fib_context = None
        if alignment_report.aligned and h1_state.strategic_origin and h1_state.strategic_endpoint:
            tick = self.feed.tick(symbol)
            fib_context = self.fib.calculate(
                direction=h1_state.trend,
                origin=h1_state.strategic_origin.price,
                endpoint=h1_state.strategic_endpoint.price,
                current=(tick.bid + tick.ask) / 2.0,
                aligned=True,
                correction_qualified=h1_state.correction_qualified,
                max_correction_depth=h1_state.correction_depth,
            ).to_dict()

        return RuntimeSnapshot(
            symbol=symbol,
            h4=h4_state.to_dict(),
            h1=h1_state.to_dict(),
            fibonacci=fib_context,
            last_h4_bar=self.store.get(self._cursor_key(symbol, "H4")),
            last_h1_bar=self.store.get(self._cursor_key(symbol, "H1")),
            alignment=alignment_report.to_dict(),
        )
