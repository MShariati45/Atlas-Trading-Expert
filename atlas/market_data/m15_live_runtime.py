from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from atlas.agents.h4_structure import PricePoint
from atlas.agents.m15_impulse_correction import M15ImpulseCorrectionAgent
from atlas.agents.m15_multiple_top_bottom import M15MultipleTopBottomAgent
from atlas.agents.m15_flag_pennant import M15FlagPennantAgent
from atlas.agents.m15_triangle_wedge import M15TriangleWedgeAgent
from atlas.agents.m15_head_shoulders import M15HeadShouldersAgent
from atlas.agents.m15_channel import M15ChannelAgent, ChannelPolicy
from atlas.agents.m15_candlestick_sr import M15CandlestickSRLiveAgent
from atlas.coordination.m15_coordinator import M15Coordinator
from atlas.core.events import Event
from atlas.core.state_store import JsonFileStateStore
from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.market_data.live_runtime import candle_payload
from atlas.market_data.mt5_feed import Candle, MT5MarketDataFeed
from atlas.strategy.profile import (
    AtlasStrategyProfile,
    PATTERN_CHANNEL_BOUNDARY,
    PATTERN_CANDLESTICK_SR,
    PATTERN_FLAG,
    PATTERN_HS,
    PATTERN_IMPULSE,
    PATTERN_MULTIPLE,
    PATTERN_TRIANGLE,
    default_m15_first_profile,
    legacy_compat_profile,
)


@dataclass(slots=True)
class M15LiveSnapshot:
    symbol: str
    permitted_direction: str
    fib_retracement_pct: float
    broad_m15_activation: bool
    new_flag_discovery_allowed: bool
    structure_risk: bool
    reports: list[dict[str, Any]]
    coordinator: dict[str, Any]
    last_m15_bar: str | None


class M15LiveSpecialistRuntime:
    """Read-only completed-bar runtime for all six M15 specialists.

    Candidate discovery is deterministic and conservative. It uses confirmed local
    swings from completed M15 bars to propose geometry to the pattern specialists;
    the specialist engines remain the authority that accepts/rejects that geometry.
    No order execution exists here.
    """
    def __init__(self, feed: MT5MarketDataFeed, store: JsonFileStateStore, strategy_profile: AtlasStrategyProfile | None = None) -> None:
        self.feed = feed
        self.store = store
        self.strategy_profile = strategy_profile or legacy_compat_profile()
        self.bootstrapper = HistoricalStructureBootstrapper(left=2, right=2, min_swings=4)
        self.impulse = M15ImpulseCorrectionAgent(store)
        self.multiple = M15MultipleTopBottomAgent(store)
        self.flag = M15FlagPennantAgent(store)
        self.triangle = M15TriangleWedgeAgent(store)
        self.hs = M15HeadShouldersAgent(store)
        self.channel = M15ChannelAgent(store, ChannelPolicy())
        self.candlestick = M15CandlestickSRLiveAgent(feed, enabled=True)
        self.coordinator = M15Coordinator()

    def _enabled(self, symbol: str, pattern: str) -> bool:
        return self.strategy_profile.pattern_rule(symbol, pattern).enabled

    def _channel_enabled(self, symbol: str) -> bool:
        return self._enabled(symbol, PATTERN_CHANNEL_BOUNDARY)

    def _cursor_key(self, symbol: str) -> str: return f"cursor:M15:{symbol}"
    def _ctx_key(self, symbol: str) -> str: return f"m15:context:{symbol}"

    @staticmethod
    def _prior_trend(direction: str) -> str:
        return "BEARISH" if direction == "LONG" else "BULLISH"

    def _seed(self, symbol: str, direction: str, fib_pct: float, bars: list[Candle]) -> None:
        result = self.bootstrapper.derive(bars)
        prior = self._prior_trend(direction)
        fib_disabled = not self.strategy_profile.fibonacci_enabled
        broad_seed_fib = 100.0 if fib_disabled else fib_pct
        flag_seed_fib = 0.0 if fib_disabled else fib_pct
        if self._enabled(symbol, PATTERN_IMPULSE):
            self.impulse.seed(symbol, trend=result.trend, control_pivot=result.control_pivot,
                              endpoint=result.endpoint, permitted_direction=direction)
        if self._enabled(symbol, PATTERN_MULTIPLE):
            self.multiple.seed(symbol, permitted_direction=direction, prior_trend=prior)
        if self._enabled(symbol, PATTERN_FLAG):
            self.flag.seed(symbol, permitted_direction=direction, fib_retracement_pct=flag_seed_fib)
        if self._enabled(symbol, PATTERN_TRIANGLE):
            self.triangle.seed(symbol, permitted_direction=direction, fib_retracement_pct=broad_seed_fib)
        if self._enabled(symbol, PATTERN_HS):
            self.hs.seed(symbol, permitted_direction=direction, prior_trend=prior, fib_retracement_pct=broad_seed_fib)
        if self._channel_enabled(symbol):
            self.channel.seed(symbol, permitted_direction=direction, fib_retracement_pct=broad_seed_fib)
        self.store.set(self._cursor_key(symbol), bars[-1].time_utc.isoformat())
        self.store.set(self._ctx_key(symbol), {
            "direction": direction, "fib_pct": fib_pct,
            "broad_active": True if fib_disabled else fib_pct >= 38.2,
            "new_flag_discovery_allowed": True if fib_disabled else fib_pct < 38.2,
        })
        # Feed confirmed pivots into Multiple Top/Bottom so it starts with real structure.
        self._emit_pivots(symbol, bars, only_latest=False)
        self._discover_candidates(
            symbol, direction, fib_pct, bars,
            broad_active=True if fib_disabled else fib_pct >= 38.2,
            new_flag_discovery_allowed=True if fib_disabled else fib_pct < 38.2,
        )

    def _needs_seed(self, symbol: str, direction: str) -> bool:
        ctx = self.store.get(self._ctx_key(symbol))
        return ctx is None or ctx.get("direction") != direction or self.store.get(self.impulse._key(symbol)) is None

    @staticmethod
    def _metrics(bars: list[Candle], meta: Any) -> tuple[float, float, float]:
        recent = bars[-20:] if len(bars) >= 20 else bars
        trs=[]; wicks=[]
        prev=None
        for b in recent:
            tr=b.high-b.low if prev is None else max(b.high-b.low, abs(b.high-prev), abs(b.low-prev))
            trs.append(tr); wicks.append(max(b.high-max(b.open,b.close), min(b.open,b.close)-b.low, 0.0)); prev=b.close
        atr=mean(trs) if trs else 0.0
        wick=mean(wicks) if wicks else 0.0
        spread=(recent[-1].spread_points * meta.point) if recent else 0.0
        return atr, wick, spread

    def _bar_payload(self, bar: Candle, bars: list[Candle]) -> dict[str, Any]:
        meta=self.feed.ensure_symbol("") if False else None
        p=candle_payload(bar)
        return p

    def _enriched(self, symbol: str, bar: Candle, history: list[Candle]) -> dict[str, Any]:
        meta=self.feed.ensure_symbol(symbol)
        atr,wick,spread=self._metrics(history, meta)
        p=candle_payload(bar); p.update({"atr":atr,"wick_stat":wick,"spread":spread,"tick_size":meta.trade_tick_size or meta.point})
        return p

    def _emit_pivots(self, symbol: str, bars: list[Candle], only_latest: bool=True) -> None:
        if not self._enabled(symbol, PATTERN_MULTIPLE):
            return
        swings=self.bootstrapper.swings(bars)
        selected=swings[-1:] if only_latest else swings[-20:]
        meta=self.feed.ensure_symbol(symbol); atr,wick,spread=self._metrics(bars,meta)
        for s in selected:
            payload={"kind":s.kind,"price":s.price,"time":s.time.isoformat(),"bar_index":s.index,
                     "atr":atr,"wick_stat":wick,"spread":spread,"tick_size":meta.trade_tick_size or meta.point}
            self.multiple.handle(Event("M15_PIVOT_CONFIRMED",symbol=symbol,timeframe="M15",payload=payload))

    def _discover_candidates(
        self,
        symbol: str,
        direction: str,
        fib_pct: float,
        bars: list[Candle],
        *,
        broad_active: bool,
        new_flag_discovery_allowed: bool,
    ) -> None:
        if len(bars)<12: return
        swings=self.bootstrapper.swings(bars)
        meta=self.feed.ensure_symbol(symbol); atr,wick,spread=self._metrics(bars,meta)
        common={"atr":atr,"wick_stat":wick,"spread":spread,"tick_size":meta.trade_tick_size or meta.point}
        # H&S from last five alternating confirmed swings.
        if broad_active and self._enabled(symbol, PATTERN_HS) and len(swings)>=5:
            s=swings[-5:]; kinds=[x.kind for x in s]
            if direction=="SHORT" and kinds==["HIGH","LOW","HIGH","LOW","HIGH"]:
                info={"pattern_type":"HEAD_SHOULDERS","left_shoulder":s[0].price,"head":s[2].price,"right_shoulder":s[4].price,
                      "neckline":mean([s[1].price,s[3].price]),"pattern_start_time":s[0].time.isoformat(),"pattern_end_time":s[4].time.isoformat(),**common}
                self.hs.handle(Event("M15_HEAD_SHOULDERS_CANDIDATE",symbol=symbol,timeframe="M15",payload=info))
            elif direction=="LONG" and kinds==["LOW","HIGH","LOW","HIGH","LOW"]:
                info={"pattern_type":"INVERSE_HEAD_SHOULDERS","left_shoulder":s[0].price,"head":s[2].price,"right_shoulder":s[4].price,
                      "neckline":mean([s[1].price,s[3].price]),"pattern_start_time":s[0].time.isoformat(),"pattern_end_time":s[4].time.isoformat(),**common}
                self.hs.handle(Event("M15_HEAD_SHOULDERS_CANDIDATE",symbol=symbol,timeframe="M15",payload=info))
        # Channel / triangle-wedge candidates from recent reaction envelopes.
        # Do not overwrite a still-fresh actionable trigger with a newly
        # rediscovered version of the same evolving geometry. The specialist
        # must first age the trigger to STALE (or invalidate it) before discovery
        # can register a new candidate.
        triangle_raw=self.store.get(self.triangle._key(symbol)) or {}
        triangle_discovery_open=(not self._enabled(symbol, PATTERN_TRIANGLE)) or triangle_raw.get("pattern_state") != "VALID_TRIGGER"
        if broad_active and (self._enabled(symbol, PATTERN_TRIANGLE) or self._channel_enabled(symbol)) and triangle_discovery_open and len(swings)>=6:
            ss=swings[-8:]; highs=[x for x in ss if x.kind=="HIGH"]; lows=[x for x in ss if x.kind=="LOW"]
            if len(highs)>=2 and len(lows)>=2:
                upper=mean([x.price for x in highs[-2:]]); lower=mean([x.price for x in lows[-2:]])
                hslope=highs[-1].price-highs[-2].price; lslope=lows[-1].price-lows[-2].price
                ctype="DESCENDING_CHANNEL" if direction=="LONG" else "ASCENDING_CHANNEL"
                if self._channel_enabled(symbol) and ((direction=="LONG" and hslope<=0 and lslope<=0) or (direction=="SHORT" and hslope>=0 and lslope>=0)):
                    self.channel.handle(Event("M15_CHANNEL_CANDIDATE",symbol=symbol,timeframe="M15",payload={"channel_type":ctype,"upper_boundary":upper,"lower_boundary":lower,"reaction_highs":len(highs),"reaction_lows":len(lows),"upper_slope":hslope,"lower_slope":lslope,"stop_anchor":lower if direction=="LONG" else upper}))
                # Classify triangle/wedge geometry from the two most recent
                # confirmed reaction highs and lows. Flatness is volatility-aware
                # so tiny quote noise does not turn a horizontal boundary into a
                # slope. Pattern geometry is separate from breakout direction; the
                # specialist still enforces the HTF-permitted breakout.
                flat_tol=max(atr*0.20, (meta.trade_tick_size or meta.point)*4.0)
                high_flat=abs(hslope)<=flat_tol
                low_flat=abs(lslope)<=flat_tol
                ptype=None
                if high_flat and lslope>flat_tol and direction=="LONG":
                    ptype="ASCENDING_TRIANGLE"
                elif hslope < -flat_tol and low_flat and direction=="SHORT":
                    ptype="DESCENDING_TRIANGLE"
                elif hslope < -flat_tol and lslope > flat_tol:
                    ptype="SYMMETRICAL_TRIANGLE"
                elif hslope > flat_tol and lslope > flat_tol and lslope > hslope + flat_tol and direction=="SHORT":
                    ptype="RISING_WEDGE"
                elif hslope < -flat_tol and lslope < -flat_tol and hslope < lslope - flat_tol and direction=="LONG":
                    ptype="FALLING_WEDGE"
                if ptype is not None and self._enabled(symbol, PATTERN_TRIANGLE):
                    # Use the nearest validated structural obstacle beyond the
                    # pattern boundary, not the most extreme historical swing.
                    # Atlas requires the *first* meaningful S/R that price must
                    # clear after escaping the formation.
                    # Exclude the reaction swings that define the current
                    # formation; the first obstacle must be external structure,
                    # not another point already inside the pattern geometry.
                    prior_swings=swings[:-len(ss)] if len(swings)>len(ss) else []
                    prior_highs=[x.price for x in prior_swings if x.kind=="HIGH" and x.price>upper]
                    prior_lows=[x.price for x in prior_swings if x.kind=="LOW" and x.price<lower]
                    # A triangle/wedge is not actionable without an actual
                    # validated external M15 obstacle. Do not synthesize one from
                    # ATR: the specialist's structural-break gate must refer to
                    # observed market structure.
                    if direction=="LONG" and prior_highs:
                        first_sr=min(prior_highs)
                        self.triangle.handle(Event("M15_TRIANGLE_WEDGE_CANDIDATE",symbol=symbol,timeframe="M15",payload={"pattern_type":ptype,"upper_boundary":upper,"lower_boundary":lower,"reaction_highs":len(highs),"reaction_lows":len(lows),"first_structural_sr":first_sr,"stop_anchor":lower}))
                    elif direction=="SHORT" and prior_lows:
                        first_sr=max(prior_lows)
                        self.triangle.handle(Event("M15_TRIANGLE_WEDGE_CANDIDATE",symbol=symbol,timeframe="M15",payload={"pattern_type":ptype,"upper_boundary":upper,"lower_boundary":lower,"reaction_highs":len(highs),"reaction_lows":len(lows),"first_structural_sr":first_sr,"stop_anchor":upper}))
        # Flag/pennant: build the pattern from bars *before* the current bar.
        # The current completed M15 candle is evaluated later by update_bar as
        # the potential breakout candle. Including it in the consolidation would
        # make a normal close beyond the consolidation high/low impossible.
        flag_context=bars[:-1]
        flag_raw=self.store.get(self.flag._key(symbol)) or {}
        flag_discovery_open=flag_raw.get("pattern_state") != "VALID_TRIGGER"
        if new_flag_discovery_allowed and flag_discovery_open and len(flag_context)>=10:
            pole=flag_context[-10:-4]; cons=flag_context[-4:]
            origin=pole[0].open; endpoint=pole[-1].close; move=endpoint-origin
            if (direction=="LONG" and move>0) or (direction=="SHORT" and move<0):
                self.flag.handle(Event("M15_FLAGPOLE_CANDIDATE",symbol=symbol,timeframe="M15",payload={"origin":origin,"endpoint":endpoint,"bars":len(pole),"atr":max(atr,1e-12)}))
                # A pennant is a short converging consolidation; a flag is the
                # non-converging/roughly channel-like member of the same family.
                # Compare the first and second halves of the frozen four-bar
                # consolidation, using ATR-aware tolerance to avoid classifying
                # quote noise as convergence.
                first=cons[:2]; second=cons[2:]
                first_high=max(x.high for x in first); second_high=max(x.high for x in second)
                first_low=min(x.low for x in first); second_low=min(x.low for x in second)
                shape_tol=max(atr*0.10, (meta.trade_tick_size or meta.point)*3.0)
                first_range=first_high-first_low; second_range=second_high-second_low
                converging=(second_high < first_high-shape_tol and second_low > first_low+shape_tol and second_range < first_range)
                shape="PENNANT" if converging else "FLAG"
                self.flag.handle(Event("M15_CONSOLIDATION_UPDATE",symbol=symbol,timeframe="M15",payload={"high":max(x.high for x in cons),"low":min(x.low for x in cons),"bars":len(cons),"shape":shape}))

    def poll(
        self,
        symbol: str,
        direction: str,
        fib_pct: float,
        history_count: int = 240,
        *,
        broad_m15_activation: bool | None = None,
        new_flag_discovery_allowed: bool | None = None,
        structure_risk: bool = False,
    ) -> M15LiveSnapshot:
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        # Backward-compatible defaults preserve the pre-v0.21.5 caller contract,
        # while live callers should pass the frozen Fibonacci permissions.
        if not self.strategy_profile.fibonacci_enabled:
            broad_active = True
            new_flag_allowed = True
            structure_risk = False
        else:
            broad_active = (fib_pct >= 38.2) if broad_m15_activation is None else bool(broad_m15_activation)
            new_flag_allowed = (fib_pct < 38.2) if new_flag_discovery_allowed is None else bool(new_flag_discovery_allowed)
            if structure_risk:
                broad_active = False
                new_flag_allowed = False

        bars = self.feed.closed_bars(symbol, "M15", history_count)
        if len(bars) < 30:
            raise ValueError("INSUFFICIENT_M15_HISTORY")
        if self._needs_seed(symbol, direction):
            self._seed(symbol, direction, fib_pct, bars)

        # Refresh specialist activation from the actual H1/Fibonacci handoff, not
        # from the instantaneous retracement alone. This is what preserves the
        # >=38.2% latch during recovery below 38.2%.
        fib_event = Event(
            "FIB_CONTEXT_UPDATE",
            symbol=symbol,
            timeframe="M15",
            payload={
                "retracement_pct": fib_pct,
                "broad_m15_activation": broad_active,
                "new_flag_discovery_allowed": new_flag_allowed,
                "structure_risk": structure_risk,
            },
        )
        if self.strategy_profile.fibonacci_enabled:
            for a, enabled in (
                (self.flag, self._enabled(symbol, PATTERN_FLAG)),
                (self.triangle, self._enabled(symbol, PATTERN_TRIANGLE)),
                (self.hs, self._enabled(symbol, PATTERN_HS)),
                (self.channel, self._channel_enabled(symbol)),
            ):
                if enabled:
                    a.handle(fib_event)

        prior_ctx = self.store.get(self._ctx_key(symbol)) or {}
        prior_broad = bool(prior_ctx.get("broad_active", False))
        self.store.set(
            self._ctx_key(symbol),
            {
                "direction": direction,
                "fib_pct": fib_pct,
                "broad_active": broad_active,
                "new_flag_discovery_allowed": new_flag_allowed,
                "structure_risk": structure_risk,
            },
        )

        # When the broad layer wakes for the first time, refresh its structural
        # context from completed history so it did not need to process shallow
        # Flag-only bars while asleep.
        if self.strategy_profile.fibonacci_enabled and broad_active and not prior_broad and len(bars) >= 2:
            hist = bars[:-1]
            result = self.bootstrapper.derive(hist)
            self.impulse.seed(
                symbol,
                trend=result.trend,
                control_pivot=result.control_pivot,
                endpoint=result.endpoint,
                permitted_direction=direction,
            )
            prior = self._prior_trend(direction)
            self.multiple.seed(symbol, permitted_direction=direction, prior_trend=prior)
            self.triangle.seed(symbol, permitted_direction=direction, fib_retracement_pct=fib_pct)
            self.hs.seed(symbol, permitted_direction=direction, prior_trend=prior, fib_retracement_pct=fib_pct)
            self.channel.seed(symbol, permitted_direction=direction, fib_retracement_pct=fib_pct)
            # Re-apply the latch override after seed, then rebuild broad pattern
            # candidates from the completed history immediately preceding the
            # latest bar.
            for a in (self.triangle, self.hs, self.channel):
                a.handle(fib_event)
            self._emit_pivots(symbol, hist, only_latest=False)
            self._discover_candidates(
                symbol,
                direction,
                fib_pct,
                hist,
                broad_active=True,
                new_flag_discovery_allowed=False,
            )

        cursor = self.store.get(self._cursor_key(symbol))
        new = [b for b in bars if cursor is None or b.time_utc.isoformat() > cursor]
        reports = []
        for bar in new:
            prefix = [x for x in bars if x.time_utc <= bar.time_utc]
            if broad_active:
                self._emit_pivots(symbol, prefix, only_latest=True)
            self._discover_candidates(
                symbol,
                direction,
                fib_pct,
                prefix,
                broad_active=broad_active,
                new_flag_discovery_allowed=new_flag_allowed,
            )
            payload = self._enriched(symbol, bar, prefix)
            ev = Event("M15_BAR_CLOSED", symbol=symbol, timeframe="M15", payload=payload)
            active_agents = []
            if broad_active:
                if self._enabled(symbol, PATTERN_IMPULSE): active_agents.append(self.impulse)
                if self._enabled(symbol, PATTERN_MULTIPLE): active_agents.append(self.multiple)
                if self._enabled(symbol, PATTERN_TRIANGLE): active_agents.append(self.triangle)
                if self._enabled(symbol, PATTERN_HS): active_agents.append(self.hs)
                if self._channel_enabled(symbol): active_agents.append(self.channel)
            # A mature flag may continue after the old Fibonacci handoff; when
            # Fibonacci is disabled, discovery remains open continuously.
            flag_raw = self.store.get(self.flag._key(symbol)) or {}
            flag_carryover = bool(flag_raw.get("mature_carryover_allowed", False))
            if self._enabled(symbol, PATTERN_FLAG) and (new_flag_allowed or flag_carryover):
                active_agents.append(self.flag)
            for a in active_agents:
                r = a.handle(ev)
                if r is not None:
                    reports.append(r.to_dict())
            self.store.set(self._cursor_key(symbol), bar.time_utc.isoformat())

        # Always expose all six specialist states for audit/dashboard purposes.
        current = []
        configured_agents = (
            (self.impulse, self._enabled(symbol, PATTERN_IMPULSE)),
            (self.multiple, self._enabled(symbol, PATTERN_MULTIPLE)),
            (self.flag, self._enabled(symbol, PATTERN_FLAG)),
            (self.triangle, self._enabled(symbol, PATTERN_TRIANGLE)),
            (self.hs, self._enabled(symbol, PATTERN_HS)),
            (self.channel, self._channel_enabled(symbol)),
        )
        for a, enabled in configured_agents:
            if not enabled:
                continue
            raw = self.store.get(a._key(symbol))
            if raw is not None:
                status = raw.get("phase") or raw.get("pattern_state") or "UNKNOWN"
                current.append({
                    "agent_id": a.agent_id,
                    "status": status,
                    "data": raw,
                    "reason_codes": [raw.get("last_reason_code", "UNKNOWN")],
                })

        # Selective candlestick-at-major-S/R specialist. This agent is independent
        # of H4/H1 direction and only emits whitelisted symbol/pattern/SR setups.
        if self._enabled(symbol, PATTERN_CANDLESTICK_SR):
            candle_report = self.candlestick.evaluate(symbol, direction, bars)
            if candle_report is not None:
                current.append(candle_report)

        flag_raw = self.store.get(self.flag._key(symbol)) or {}
        flag_carryover = bool(flag_raw.get("mature_carryover_allowed", False))
        eligible: set[str] = set()
        if broad_active:
            if self._enabled(symbol, PATTERN_IMPULSE): eligible.add("M15_IMPULSE_CORRECTION")
            if self._enabled(symbol, PATTERN_MULTIPLE): eligible.add("M15_MULTIPLE_TOP_BOTTOM")
            if self._enabled(symbol, PATTERN_TRIANGLE): eligible.add("M15_TRIANGLE_WEDGE")
            if self._enabled(symbol, PATTERN_HS): eligible.add("M15_HEAD_SHOULDERS")
            if self._channel_enabled(symbol): eligible.add("M15_CHANNEL")
        if self._enabled(symbol, PATTERN_FLAG) and (new_flag_allowed or flag_carryover):
            eligible.add("M15_FLAG_PENNANT")
        if self._enabled(symbol, PATTERN_CANDLESTICK_SR):
            eligible.add("M15_CANDLESTICK_SR")

        blocked_reason = "M15_BLOCKED_BY_H1_STRUCTURE_RISK" if structure_risk else None
        if not structure_risk and not eligible:
            blocked_reason = "M15_NO_ELIGIBLE_SPECIALISTS"
        pkg = self.coordinator.build(
            symbol,
            direction,
            current,
            eligible_agents=eligible,
            blocked_reason=blocked_reason,
        ).to_dict()
        return M15LiveSnapshot(
            symbol,
            direction,
            fib_pct,
            broad_active,
            new_flag_allowed,
            structure_risk,
            current,
            pkg,
            self.store.get(self._cursor_key(symbol)),
        )
