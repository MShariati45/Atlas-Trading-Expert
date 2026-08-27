from types import SimpleNamespace

from atlas.execution.models import AccountConfig
from atlas.market_data.mt5_feed import MT5MarketDataFeed


class FakeMT5:
    TIMEFRAME_H4 = 240
    TIMEFRAME_H1 = 60
    TIMEFRAME_M15 = 15
    TIMEFRAME_M5 = 5
    TIMEFRAME_M1 = 1
    TIMEFRAME_M30 = 30
    TIMEFRAME_D1 = 1440

    def __init__(self):
        self.init_kwargs = None
        self.selected = []
        self.rate_start_pos = None

    def initialize(self, **kwargs):
        self.init_kwargs = kwargs
        return True

    def shutdown(self):
        return True

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True, build=1234)

    def version(self):
        return (5, 0, 1234, "2026-08-18")

    def account_info(self):
        return SimpleNamespace(login=123, server="Demo", currency="USD", balance=10000.0,
                               equity=10020.0, margin=100.0, margin_free=9920.0,
                               leverage=100, trade_allowed=True)

    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.00001, digits=5, trade_tick_size=0.00001,
                               trade_tick_value=1.0, volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, trade_stops_level=10, trade_freeze_level=0,
                               visible=True)

    def symbol_select(self, symbol, enabled):
        self.selected.append((symbol, enabled))
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=1_700_000_000, bid=1.1000, ask=1.1002, last=1.1001, volume=10)

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.rate_start_pos = start_pos
        return [
            {"time": 1_700_000_000 + i * 60, "open": 1.0, "high": 1.2,
             "low": 0.9, "close": 1.1, "tick_volume": 100+i,
             "spread": 12, "real_volume": 0}
            for i in range(count)
        ]

    def positions_get(self, **kwargs):
        return []


def feed_with_fake():
    feed = MT5MarketDataFeed()
    feed._mt5 = FakeMT5()
    return feed


def test_reads_account_tick_symbol_and_completed_bars():
    feed = feed_with_fake()
    feed.connect(AccountConfig("DEMO", True, 0.5))
    assert feed.terminal_health()["terminal_connected"] is True
    assert feed.account_snapshot().equity == 10020.0
    assert feed.ensure_symbol("EURUSD").digits == 5
    assert round(feed.tick("EURUSD").spread_price, 5) == 0.0002
    bars = feed.closed_bars("EURUSD", "H4", 3)
    assert len(bars) == 3
    assert feed._mt5.rate_start_pos == 1  # current forming candle must be excluded


def test_invalid_timeframe_rejected():
    feed = feed_with_fake()
    try:
        feed.closed_bars("EURUSD", "H2", 2)
    except ValueError as exc:
        assert "Unsupported timeframe" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_broker_symbol_mapping_keeps_canonical_strategy_symbol():
    from atlas.execution.mt5_bridge import MT5ConnectionSettings
    feed = MT5MarketDataFeed({"DEMO": MT5ConnectionSettings(symbol_map={"EURUSD": "EURUSD.a"})})
    fake = FakeMT5()
    feed._mt5 = fake
    feed.connect(AccountConfig("DEMO", True, 0.5))
    meta = feed.ensure_symbol("EURUSD")
    assert meta.symbol == "EURUSD.a"
    tick = feed.tick("EURUSD")
    assert tick.symbol == "EURUSD"
    assert feed.broker_symbol("EURUSD") == "EURUSD.a"
