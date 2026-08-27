from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from atlas.execution.mt5_bridge import MT5ConnectionSettings, MetaTrader5Unavailable
from atlas.execution.models import AccountConfig


@dataclass(slots=True, frozen=True)
class Candle:
    time_utc: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread_points: int
    real_volume: int


@dataclass(slots=True, frozen=True)
class TickSnapshot:
    symbol: str
    time_utc: datetime
    bid: float
    ask: float
    last: float
    volume: float

    @property
    def spread_price(self) -> float:
        return max(0.0, self.ask - self.bid)


@dataclass(slots=True, frozen=True)
class SymbolSnapshot:
    symbol: str
    point: float
    digits: int
    trade_tick_size: float
    trade_tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int
    freeze_level_points: int
    visible: bool


@dataclass(slots=True, frozen=True)
class AccountSnapshot:
    login: int
    server: str
    currency: str
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: int
    trade_allowed: bool


class MT5MarketDataFeed:
    """Read-only MetaTrader 5 data feed used by Atlas.

    This adapter intentionally has no order-send method. Live/demo execution remains
    in the separate execution bridge, which is disabled by default by Atlas config.
    """

    TIMEFRAMES = {
        "M1": "TIMEFRAME_M1",
        "M5": "TIMEFRAME_M5",
        "M15": "TIMEFRAME_M15",
        "M30": "TIMEFRAME_M30",
        "H1": "TIMEFRAME_H1",
        "H4": "TIMEFRAME_H4",
        "D1": "TIMEFRAME_D1",
    }

    def __init__(self, settings_by_account: dict[str, MT5ConnectionSettings] | None = None) -> None:
        self.settings_by_account = settings_by_account or {}
        self._mt5: Any = None
        self._connected_account_id: str | None = None
        self._symbol_map: dict[str, str] = {}

    def _module(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except Exception as exc:
                raise MetaTrader5Unavailable(
                    "MetaTrader5 Python package/terminal is not available"
                ) from exc
            self._mt5 = mt5
        return self._mt5

    def connect(self, account: AccountConfig) -> None:
        mt5 = self._module()
        settings = self.settings_by_account.get(account.account_id, MT5ConnectionSettings())
        kwargs: dict[str, Any] = {}
        if settings.terminal_path:
            kwargs["path"] = settings.terminal_path
        if settings.login is not None:
            kwargs["login"] = settings.login
        if settings.password:
            kwargs["password"] = settings.password
        if settings.server:
            kwargs["server"] = settings.server
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self._connected_account_id = account.account_id
        self._symbol_map = dict(settings.symbol_map or {})

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
        self._connected_account_id = None
        self._symbol_map = {}

    def broker_symbol(self, symbol: str) -> str:
        """Translate Atlas canonical symbol to the connected broker symbol."""
        return self._symbol_map.get(symbol.upper(), symbol)

    def terminal_health(self) -> dict[str, Any]:
        mt5 = self._module()
        terminal = mt5.terminal_info()
        version = mt5.version()
        if terminal is None:
            raise RuntimeError(f"MT5 terminal_info failed: {mt5.last_error()}")
        return {
            "connected_account_id": self._connected_account_id,
            "terminal_connected": bool(getattr(terminal, "connected", False)),
            "trade_allowed": bool(getattr(terminal, "trade_allowed", False)),
            "build": int(getattr(terminal, "build", 0)),
            "version": list(version) if version else None,
        }

    def account_snapshot(self) -> AccountSnapshot:
        mt5 = self._module()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
        return AccountSnapshot(
            login=int(info.login),
            server=str(info.server),
            currency=str(info.currency),
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            margin_free=float(info.margin_free),
            leverage=int(info.leverage),
            trade_allowed=bool(info.trade_allowed),
        )

    def ensure_symbol(self, symbol: str) -> SymbolSnapshot:
        mt5 = self._module()
        broker_symbol = self.broker_symbol(symbol)
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            raise RuntimeError(f"Symbol {symbol} not found in MT5")
        if not bool(info.visible):
            if not mt5.symbol_select(broker_symbol, True):
                raise RuntimeError(f"Unable to select symbol {symbol} ({broker_symbol}): {mt5.last_error()}")
            info = mt5.symbol_info(broker_symbol)
            if info is None:
                raise RuntimeError(f"Symbol {symbol} unavailable after selection")
        return SymbolSnapshot(
            symbol=broker_symbol,
            point=float(info.point),
            digits=int(info.digits),
            trade_tick_size=float(getattr(info, "trade_tick_size", 0.0)),
            trade_tick_value=float(getattr(info, "trade_tick_value", 0.0)),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            stops_level_points=int(getattr(info, "trade_stops_level", 0)),
            freeze_level_points=int(getattr(info, "trade_freeze_level", 0)),
            visible=bool(info.visible),
        )

    def tick(self, symbol: str) -> TickSnapshot:
        mt5 = self._module()
        self.ensure_symbol(symbol)
        broker_symbol = self.broker_symbol(symbol)
        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise RuntimeError(f"No tick available for {symbol}")
        epoch = int(getattr(tick, "time", 0))
        return TickSnapshot(
            symbol=symbol,
            time_utc=datetime.fromtimestamp(epoch, tz=timezone.utc),
            bid=float(tick.bid),
            ask=float(tick.ask),
            last=float(getattr(tick, "last", 0.0)),
            volume=float(getattr(tick, "volume", 0.0)),
        )

    def closed_bars(self, symbol: str, timeframe: str, count: int = 300) -> list[Candle]:
        """Return completed candles only, oldest -> newest.

        MT5 position 0 is the currently forming candle, so Atlas starts at position 1.
        This prevents incomplete bars from mutating validated structure state.
        """
        if count <= 0:
            return []
        mt5 = self._module()
        self.ensure_symbol(symbol)
        tf_name = self.TIMEFRAMES.get(timeframe.upper())
        if tf_name is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        tf = getattr(mt5, tf_name)
        broker_symbol = self.broker_symbol(symbol)
        rates = mt5.copy_rates_from_pos(broker_symbol, tf, 1, int(count))
        if rates is None:
            raise RuntimeError(f"MT5 rates read failed for {symbol} {timeframe}: {mt5.last_error()}")
        candles: list[Candle] = []
        for row in rates:
            candles.append(Candle(
                time_utc=datetime.fromtimestamp(int(row["time"]), tz=timezone.utc),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_volume=int(row["tick_volume"]),
                spread_points=int(row["spread"]),
                real_volume=int(row["real_volume"]),
            ))
        candles.sort(key=lambda c: c.time_utc)
        return candles

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        mt5 = self._module()
        positions = mt5.positions_get(symbol=self.broker_symbol(symbol)) if symbol else mt5.positions_get()
        if positions is None:
            raise RuntimeError(f"MT5 positions_get failed: {mt5.last_error()}")
        result: list[dict[str, Any]] = []
        for p in positions:
            result.append({
                "ticket": int(p.ticket),
                "symbol": str(p.symbol),
                "type": int(p.type),
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "price_current": float(p.price_current),
                "profit": float(p.profit),
            })
        return result

    @staticmethod
    def snapshot_dict(value: Any) -> dict[str, Any]:
        return asdict(value)

    def bars_range(self, symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime) -> list[Candle]:
        """Return completed candles in an explicit UTC range, oldest -> newest.

        The returned dataset excludes any bar whose open time is at/after end_utc.
        Callers should choose an end time safely behind the currently-forming bar
        when strict completed-bar history is required.
        """
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("start_utc and end_utc must be timezone-aware")
        if end_utc <= start_utc:
            raise ValueError("end_utc must be after start_utc")
        mt5 = self._module()
        self.ensure_symbol(symbol)
        tf_name = self.TIMEFRAMES.get(timeframe.upper())
        if tf_name is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        tf = getattr(mt5, tf_name)
        broker_symbol = self.broker_symbol(symbol)
        rates = mt5.copy_rates_range(broker_symbol, tf, start_utc, end_utc)
        if rates is None:
            raise RuntimeError(f"MT5 range read failed for {symbol} {timeframe}: {mt5.last_error()}")
        candles: list[Candle] = []
        for row in rates:
            ts = datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)
            if ts >= end_utc:
                continue
            candles.append(Candle(
                time_utc=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_volume=int(row["tick_volume"]),
                spread_points=int(row["spread"]),
                real_volume=int(row["real_volume"]),
            ))
        candles.sort(key=lambda c: c.time_utc)
        return candles
