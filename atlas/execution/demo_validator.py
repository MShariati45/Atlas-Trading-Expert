from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings, MT5PythonBridge
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.services.news_mapping import currencies_for_symbols


DEFAULT_HISTORY_REQUIREMENTS = {"D1": 500, "H4": 900, "H1": 600, "M15": 240}
DEFAULT_MAX_AGE_SECONDS = {"D1": 4 * 86400, "H4": 12 * 3600, "H1": 4 * 3600, "M15": 90 * 60}


@dataclass(slots=True)
class TimeframeReadiness:
    timeframe: str
    requested_bars: int
    returned_bars: int
    latest_closed_bar_utc: str | None
    age_seconds: float | None
    history_ok: bool
    freshness_ok: bool


@dataclass(slots=True)
class SymbolReadiness:
    canonical_symbol: str
    broker_symbol: str | None = None
    metadata_ok: bool = False
    tick_ok: bool = False
    tick_time_utc: str | None = None
    tick_age_seconds: float | None = None
    tick_freshness_ok: bool = False
    spread_points: float | None = None
    point: float | None = None
    digits: int | None = None
    trade_tick_size: float | None = None
    trade_tick_value: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    volume_step: float | None = None
    stops_level_points: int | None = None
    freeze_level_points: int | None = None
    timeframes: dict[str, TimeframeReadiness] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def history_ok(self) -> bool:
        return bool(self.timeframes) and all(x.history_ok for x in self.timeframes.values())

    @property
    def freshness_ok(self) -> bool:
        return self.tick_freshness_ok and bool(self.timeframes) and all(x.freshness_ok for x in self.timeframes.values())


@dataclass(slots=True)
class DemoReadinessReport:
    connected: bool
    account_ok: bool
    expected_account_match: bool | None
    symbols_ok: bool
    history_ok: bool
    freshness_ok: bool
    news_ok: bool
    cost_policy_ok: bool
    execution_locked: bool
    execution_enabled: bool
    terminal: dict[str, Any]
    account: dict[str, Any]
    symbols: dict[str, SymbolReadiness]
    notes: list[str]

    @property
    def ready_for_observation(self) -> bool:
        return (
            self.connected
            and self.account_ok
            and self.expected_account_match is not False
            and self.symbols_ok
            and self.history_ok
            and self.freshness_ok
            and self.execution_locked
        )

    @property
    def ready_for_paper_supervision(self) -> bool:
        return self.ready_for_observation and self.news_ok and self.cost_policy_ok

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ready_for_observation"] = self.ready_for_observation
        data["ready_for_paper_supervision"] = self.ready_for_paper_supervision
        return data


class MT5DemoValidator:
    """Read-only MT5 preflight for Atlas demo readiness.

    The validator performs no order operations. It verifies the exact data surfaces
    needed by the current Atlas runtime: terminal/account identity, canonical-to-
    broker symbol mapping, symbol contract metadata, live ticks, D1/H4/H1/M15
    completed-bar history, data freshness, news-provider availability, and the
    independent hard execution lock.
    """

    def __init__(self, feed: MT5MarketDataFeed) -> None:
        self.feed = feed

    @staticmethod
    def _age_seconds(now: datetime, then: datetime) -> float:
        return max(0.0, (now - then).total_seconds())

    @staticmethod
    def _symbol_contract_ok(meta: Any) -> bool:
        return (
            meta.point > 0
            and meta.digits >= 0
            and meta.trade_tick_size > 0
            and meta.volume_min > 0
            and meta.volume_max >= meta.volume_min
            and meta.volume_step > 0
        )

    def validate(
        self,
        account: AccountConfig,
        symbols: list[str],
        *,
        now: datetime | None = None,
        expected_login: int | None = None,
        news_json: str | Path | None = None,
        cost_policy_json: str | Path | None = None,
        history_requirements: dict[str, int] | None = None,
        max_age_seconds: dict[str, int] | None = None,
        max_tick_age_seconds: int = 600,
    ) -> DemoReadinessReport:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        history_requirements = dict(history_requirements or DEFAULT_HISTORY_REQUIREMENTS)
        max_age_seconds = dict(max_age_seconds or DEFAULT_MAX_AGE_SECONDS)
        notes: list[str] = []
        connected = account_ok = symbols_ok = history_ok = freshness_ok = False
        expected_account_match: bool | None = None
        terminal_info: dict[str, Any] = {}
        account_info: dict[str, Any] = {}
        symbol_reports: dict[str, SymbolReadiness] = {}
        news_ok = False
        cost_policy_ok = False

        try:
            self.feed.connect(account)
            terminal_info = dict(self.feed.terminal_health())
            connected = bool(terminal_info.get("terminal_connected")) and int(terminal_info.get("build", 0) or 0) > 0
            if not connected:
                notes.append("MT5_TERMINAL_NOT_CONNECTED_OR_BUILD_INVALID")

            snapshot = self.feed.account_snapshot()
            account_info = asdict(snapshot)
            account_ok = snapshot.login > 0 and snapshot.equity > 0 and snapshot.balance >= 0 and bool(snapshot.server)
            if not snapshot.trade_allowed:
                notes.append("MT5_TRADE_ALLOWED_FALSE_OBSERVATION_STILL_POSSIBLE")
            if expected_login is not None:
                expected_account_match = snapshot.login == int(expected_login)
                if not expected_account_match:
                    notes.append(f"ACCOUNT_LOGIN_MISMATCH_EXPECTED_{expected_login}_ACTUAL_{snapshot.login}")

            symbols_ok = True
            history_ok = True
            freshness_ok = True
            for canonical in symbols:
                sr = SymbolReadiness(canonical_symbol=canonical)
                symbol_reports[canonical] = sr
                try:
                    meta = self.feed.ensure_symbol(canonical)
                    sr.broker_symbol = meta.symbol
                    sr.metadata_ok = self._symbol_contract_ok(meta)
                    sr.point = meta.point
                    sr.digits = meta.digits
                    sr.trade_tick_size = meta.trade_tick_size
                    sr.trade_tick_value = meta.trade_tick_value
                    sr.volume_min = meta.volume_min
                    sr.volume_max = meta.volume_max
                    sr.volume_step = meta.volume_step
                    sr.stops_level_points = meta.stops_level_points
                    sr.freeze_level_points = meta.freeze_level_points
                    if not sr.metadata_ok:
                        sr.notes.append("SYMBOL_CONTRACT_METADATA_INVALID")
                        symbols_ok = False
                except Exception as exc:
                    sr.notes.append(f"SYMBOL_METADATA_FAILED: {exc}")
                    symbols_ok = False
                    history_ok = False
                    freshness_ok = False
                    continue

                try:
                    tick = self.feed.tick(canonical)
                    sr.tick_ok = tick.bid > 0 and tick.ask > 0 and tick.ask >= tick.bid
                    sr.tick_time_utc = tick.time_utc.isoformat()
                    sr.tick_age_seconds = self._age_seconds(now, tick.time_utc)
                    sr.tick_freshness_ok = sr.tick_ok and sr.tick_age_seconds <= max_tick_age_seconds
                    if sr.point and sr.point > 0:
                        sr.spread_points = tick.spread_price / sr.point
                    if not sr.tick_ok:
                        sr.notes.append("TICK_VALUES_INVALID")
                    if not sr.tick_freshness_ok:
                        sr.notes.append("TICK_STALE")
                        freshness_ok = False
                except Exception as exc:
                    sr.notes.append(f"TICK_READ_FAILED: {exc}")
                    freshness_ok = False

                for tf, required in history_requirements.items():
                    latest = None
                    returned = 0
                    age = None
                    tf_history_ok = False
                    tf_freshness_ok = False
                    try:
                        bars = self.feed.closed_bars(canonical, tf, required)
                        returned = len(bars)
                        tf_history_ok = returned >= required
                        if bars:
                            latest_dt = bars[-1].time_utc.astimezone(timezone.utc)
                            latest = latest_dt.isoformat()
                            age = self._age_seconds(now, latest_dt)
                            tf_freshness_ok = age <= float(max_age_seconds.get(tf, 10**12))
                        if not tf_history_ok:
                            sr.notes.append(f"{tf}_INSUFFICIENT_HISTORY_{returned}_OF_{required}")
                        if not tf_freshness_ok:
                            sr.notes.append(f"{tf}_STALE")
                    except Exception as exc:
                        sr.notes.append(f"{tf}_READ_FAILED: {exc}")
                    sr.timeframes[tf] = TimeframeReadiness(tf, required, returned, latest, age, tf_history_ok, tf_freshness_ok)
                    if not tf_history_ok:
                        history_ok = False
                    if not tf_freshness_ok:
                        freshness_ok = False

            symbols_ok = symbols_ok and all(x.metadata_ok for x in symbol_reports.values())
            history_ok = history_ok and all(x.history_ok for x in symbol_reports.values())
            freshness_ok = freshness_ok and all(x.freshness_ok for x in symbol_reports.values())

            if news_json is None:
                notes.append("LIVE_NEWS_JSON_NOT_CONFIGURED_PAPER_SUPERVISION_NOT_READY")
            else:
                provider = JsonScheduledNewsProvider(news_json, strict_freshness=True, min_validity_seconds=6 * 3600, strict_provenance=True, required_currencies=currencies_for_symbols(symbols))
                provider.events(now)
                news_ok = bool(provider.status.available)
                if not news_ok:
                    notes.append(f"LIVE_NEWS_PROVIDER_UNAVAILABLE: {provider.status.error}")
                elif provider.status.event_count == 0:
                    notes.append("LIVE_NEWS_PROVIDER_LOADED_ZERO_EVENTS_VERIFY_CALENDAR_WINDOW")

            if cost_policy_json is None:
                notes.append("BROKER_COST_POLICY_NOT_CONFIGURED_PAPER_SUPERVISION_NOT_READY")
            else:
                try:
                    from atlas.services.broker_cost_policy import load_broker_cost_policy
                    cost_status = load_broker_cost_policy(cost_policy_json, tuple(symbols))
                    cost_policy_ok = cost_status.approved
                    if not cost_policy_ok:
                        notes.extend(cost_status.reason_codes or ("BROKER_COST_POLICY_INVALID_OR_NOT_APPROVED",))
                except Exception as exc:
                    notes.append(f"BROKER_COST_POLICY_UNAVAILABLE: {exc}")
        except Exception as exc:
            notes.append(f"DEMO_PREFLIGHT_EXCEPTION: {exc}")

        bridge = MT5PythonBridge()
        execution_locked = not bridge.execution_enabled
        if not execution_locked:
            notes.append("CRITICAL_EXECUTION_LOCK_NOT_ACTIVE")

        return DemoReadinessReport(
            connected=connected,
            account_ok=account_ok,
            expected_account_match=expected_account_match,
            symbols_ok=symbols_ok,
            history_ok=history_ok,
            freshness_ok=freshness_ok,
            news_ok=news_ok,
            cost_policy_ok=cost_policy_ok,
            execution_locked=execution_locked,
            execution_enabled=not execution_locked,
            terminal=terminal_info,
            account=account_info,
            symbols=symbol_reports,
            notes=notes,
        )
