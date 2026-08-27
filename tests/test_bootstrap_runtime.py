from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime
from atlas.market_data.mt5_feed import Candle, TickSnapshot


def series(values):
    out=[]
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    for i,v in enumerate(values):
        out.append(Candle(start+timedelta(hours=i), v-0.1, v+0.2, v-0.2, v, 100,1,0))
    return out


def bullish_history():
    return series([10,11,12,13,12,11,12,13,14,15,14,13,14,15,16,17,16,15,16,17,18,19,18,17])


def bearish_history():
    return series([20,19,18,17,18,19,18,17,16,15,16,17,16,15,14,13,14,15,14,13,12,11,12,13])


def test_bootstrap_bullish_sequence():
    r = HistoricalStructureBootstrapper(left=2,right=2).derive(bullish_history())
    assert r.trend == "BULLISH"
    assert r.control_pivot.price == r.origin.price
    assert r.endpoint.price > r.origin.price


def test_bootstrap_bearish_sequence():
    r = HistoricalStructureBootstrapper(left=2,right=2).derive(bearish_history())
    assert r.trend == "BEARISH"
    assert r.endpoint.price < r.origin.price


class FakeFeed:
    def __init__(self):
        self.h4 = bullish_history()
        self.h1 = bullish_history()
    def closed_bars(self, symbol, timeframe, count=300):
        return list(self.h4 if timeframe == "H4" else self.h1)[-count:]
    def tick(self, symbol):
        return TickSnapshot(symbol, datetime.now(timezone.utc), 17.5, 17.52, 0.0, 0.0)


def test_runtime_bootstraps_then_is_incremental(tmp_path: Path):
    feed = FakeFeed()
    rt = ReadOnlyAtlasRuntime(feed, tmp_path / "state.json")
    first = rt.poll_symbol("EURUSD")
    assert first.h4["trend"] == "BULLISH"
    first_version = first.h4["state_version"]
    second = rt.poll_symbol("EURUSD")
    assert second.h4["state_version"] == first_version

    last = feed.h4[-1]
    feed.h4.append(Candle(last.time_utc+timedelta(hours=4),17,19.5,16.8,19,100,1,0))
    third = rt.poll_symbol("EURUSD")
    assert third.h4["state_version"] == first_version + 1
    assert third.last_h4_bar == feed.h4[-1].time_utc.isoformat()
