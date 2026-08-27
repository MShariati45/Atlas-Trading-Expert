from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore
from atlas.core.structure_types import PricePoint

FIB_MAJOR_THRESHOLD = 0.382
TRENDLINE_WING = 2
TRENDLINE_BUFFER_BARS = 360
TRENDLINE_PIVOT_LIMIT = 120
TRENDLINE_MIN_ANCHOR_HOURS = 72
TRENDLINE_MIN_TOUCH_HOURS = 48


@dataclass(slots=True)
class TrendlineAnchor:
    price: float
    time: str
    kind: str  # HIGH for bearish trendline, LOW for bullish trendline


@dataclass(slots=True)
class H4TrendlineState:
    status: str = "UNAVAILABLE"
    direction: str = "NONE"  # BEARISH_LINE / BULLISH_LINE
    anchors: list[TrendlineAnchor] = field(default_factory=list)
    touch_count: int = 0
    quality: str = "NONE"  # BASE (2 touches) / STRONG (3+)
    breakout_time: str | None = None
    breakout_close: float | None = None
    confirmation_time: str | None = None
    retired_time: str | None = None
    early_direction: str = "NONE"  # BULLISH / BEARISH / NONE
    last_line_price: float | None = None


@dataclass(slots=True)
class H4StructureState:
    trend: str = "UNINITIALIZED"
    phase: str = "UNINITIALIZED"
    strategic_origin: PricePoint | None = None
    strategic_endpoint: PricePoint | None = None
    control_pivot: PricePoint | None = None
    correction_extreme: PricePoint | None = None
    correction_depth: float = 0.0
    correction_qualified: bool = False
    prior_endpoint: PricePoint | None = None
    continuation_broken: bool = False
    state_version: int = 0
    bars_processed: int = 0
    last_reason_code: str = "UNINITIALIZED"
    audit: list[dict[str, Any]] = field(default_factory=list)
    trendline: H4TrendlineState = field(default_factory=H4TrendlineState)
    recent_bars: list[dict[str, Any]] = field(default_factory=list)
    trendline_pivots: list[TrendlineAnchor] = field(default_factory=list)

    @property
    def effective_direction(self) -> str:
        if self.trendline.early_direction in {"BULLISH", "BEARISH"}:
            return self.trendline.early_direction
        return self.trend

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["effective_direction"] = self.effective_direction
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "H4StructureState":
        data = dict(raw)
        data.pop("effective_direction", None)
        for name in ("strategic_origin", "strategic_endpoint", "control_pivot", "correction_extreme", "prior_endpoint"):
            if isinstance(data.get(name), dict):
                data[name] = PricePoint(**data[name])
        if isinstance(data.get("trendline"), dict):
            tl = dict(data["trendline"])
            tl["anchors"] = [TrendlineAnchor(**x) if isinstance(x, dict) else x for x in tl.get("anchors", [])]
            data["trendline"] = H4TrendlineState(**tl)
        data["trendline_pivots"] = [
            TrendlineAnchor(**x) if isinstance(x, dict) else x for x in data.get("trendline_pivots", [])
        ]
        return cls(**data)


def _parse_time(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _line_price(a: TrendlineAnchor, b: TrendlineAnchor, at_time: str) -> float:
    ta, tb, t = _parse_time(a.time), _parse_time(b.time), _parse_time(at_time)
    total = (tb - ta).total_seconds()
    if total <= 0:
        return b.price
    slope = (b.price - a.price) / total
    return a.price + slope * (t - ta).total_seconds()


class H4StructureEngine:
    """Incremental strategic H4 structure updater plus diagonal-transition component.

    The strategic trend and the early trendline direction are intentionally separate.
    A confirmed trendline break can enable an early search direction, but it never
    silently rewrites the formal strategic H4 trend.
    """

    def seed(self, *, trend: str, origin: PricePoint, endpoint: PricePoint, control_pivot: PricePoint) -> H4StructureState:
        if trend not in {"BULLISH", "BEARISH"}:
            raise ValueError("trend must be BULLISH or BEARISH")
        return H4StructureState(
            trend=trend,
            phase=f"{trend}_IMPULSE",
            strategic_origin=origin,
            strategic_endpoint=endpoint,
            control_pivot=control_pivot,
            state_version=1,
            last_reason_code="SEEDED_VALIDATED_STRUCTURE",
        )

    def configure_trendline(self, state: H4StructureState, anchors: list[TrendlineAnchor]) -> None:
        if len(anchors) < 2:
            raise ValueError("H4 trendline requires at least two validated pivot anchors")
        anchors = sorted(anchors, key=lambda x: _parse_time(x.time))
        if state.trend == "BEARISH":
            if any(a.kind != "HIGH" for a in anchors) or anchors[-1].price >= anchors[0].price:
                raise ValueError("bearish H4 trendline requires descending HIGH pivots")
            direction = "BEARISH_LINE"
        elif state.trend == "BULLISH":
            if any(a.kind != "LOW" for a in anchors) or anchors[-1].price <= anchors[0].price:
                raise ValueError("bullish H4 trendline requires ascending LOW pivots")
            direction = "BULLISH_LINE"
        else:
            raise ValueError("formal H4 trend must be BULLISH or BEARISH")
        state.trendline = H4TrendlineState(
            status="ACTIVE",
            direction=direction,
            anchors=anchors,
            touch_count=len(anchors),
            quality="STRONG" if len(anchors) >= 3 else "BASE",
        )
        state.last_reason_code = "H4_TRENDLINE_CONFIGURED"

    def update(self, state: H4StructureState, bar: dict[str, Any], *, enable_trendline: bool = True) -> H4StructureState:
        if state.trend == "UNINITIALIZED":
            return state
        for key in ("high", "low", "close", "time"):
            if key not in bar:
                raise ValueError(f"missing H4 bar field: {key}")

        state.bars_processed += 1
        state.state_version += 1
        if enable_trendline:
            self._update_pivot_buffer(state, bar)
            self._refresh_trendline_from_pivots(state, bar)
            self._update_trendline_break_state(state, bar)
        if state.trend == "BULLISH":
            self._update_bullish(state, bar)
        else:
            self._update_bearish(state, bar)
        return state

    def _audit(self, state: H4StructureState, code: str, bar: dict[str, Any], **extra: Any) -> None:
        state.last_reason_code = code
        state.audit.append({"time": bar["time"], "reason_code": code, **extra})
        state.audit = state.audit[-150:]

    def _update_pivot_buffer(self, state: H4StructureState, bar: dict[str, Any]) -> None:
        state.recent_bars.append({
            "time": str(bar["time"]),
            "open": float(bar.get("open", bar["close"])),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
        })
        state.recent_bars = state.recent_bars[-TRENDLINE_BUFFER_BARS:]
        if len(state.recent_bars) < 2 * TRENDLINE_WING + 1:
            return
        i = len(state.recent_bars) - TRENDLINE_WING - 1
        c = state.recent_bars[i]
        left = state.recent_bars[i-TRENDLINE_WING:i]
        right = state.recent_bars[i+1:i+1+TRENDLINE_WING]
        is_high = c["high"] > max(x["high"] for x in left) and c["high"] >= max(x["high"] for x in right)
        is_low = c["low"] < min(x["low"] for x in left) and c["low"] <= min(x["low"] for x in right)
        for kind, price, valid in (("HIGH", c["high"], is_high), ("LOW", c["low"], is_low)):
            if not valid:
                continue
            p = TrendlineAnchor(price=float(price), time=str(c["time"]), kind=kind)
            if state.trendline_pivots and state.trendline_pivots[-1].time == p.time and state.trendline_pivots[-1].kind == p.kind:
                continue
            state.trendline_pivots.append(p)
        state.trendline_pivots = state.trendline_pivots[-TRENDLINE_PIVOT_LIMIT:]

    def _recent_range(self, state: H4StructureState) -> float:
        if not state.recent_bars:
            return 0.0
        return sum(x["high"] - x["low"] for x in state.recent_bars[-14:]) / max(len(state.recent_bars[-14:]), 1)

    def _refresh_trendline_from_pivots(self, state: H4StructureState, bar: dict[str, Any]) -> None:
        kind = "HIGH" if state.trend == "BEARISH" else "LOW"
        pivots = [p for p in state.trendline_pivots if p.kind == kind]
        if len(pivots) < 2:
            return
        current = state.trendline
        if current.status in {"EARLY_DIRECTION_CONFIRMED", "RETIRED"}:
            return

        tolerance = max(self._recent_range(state) * 0.30, abs(pivots[-1].price) * 0.00005)
        max_violation=tolerance*1.35
        best=None
        for i in range(len(pivots)-1):
            older=pivots[i]
            for j in range(i+1,len(pivots)):
                newer=pivots[j]
                if (_parse_time(newer.time)-_parse_time(older.time)).total_seconds() < TRENDLINE_MIN_ANCHOR_HOURS*3600:
                    continue
                valid = newer.price < older.price if state.trend == "BEARISH" else newer.price > older.price
                if not valid:
                    continue
                contained=True; raw=[]
                for p in pivots[i:j+1]:
                    lp=_line_price(older,newer,p.time)
                    delta=p.price-lp
                    if state.trend=="BEARISH" and delta>max_violation:
                        contained=False; break
                    if state.trend=="BULLISH" and delta<-max_violation:
                        contained=False; break
                    if abs(delta)<=tolerance:
                        raw.append(p)
                if not contained:
                    continue
                touches=[]
                for p in raw:
                    if not touches or (_parse_time(p.time)-_parse_time(touches[-1].time)).total_seconds() >= TRENDLINE_MIN_TOUCH_HOURS*3600:
                        touches.append(p)
                    else:
                        prev=touches[-1]
                        pe=abs(prev.price-_line_price(older,newer,prev.time))
                        e=abs(p.price-_line_price(older,newer,p.time))
                        if e<pe:
                            touches[-1]=p
                if len(touches)<2:
                    continue
                span_h=(_parse_time(newer.time)-_parse_time(older.time)).total_seconds()/3600
                touch_span_h=(_parse_time(touches[-1].time)-_parse_time(touches[0].time)).total_seconds()/3600
                score=len(touches)*1000 + span_h/2 + touch_span_h/4 + (750 if len(touches)>=3 else 0)
                item=(score,older,newer,touches)
                if best is None or item[0]>best[0]:
                    best=item
        if best is None:
            return
        _,older,newer,anchors=best
        if current.anchors and current.anchors[0].time==older.time and current.anchors[-1].time==newer.time and current.touch_count==len(anchors):
            return
        self.configure_trendline(state, anchors)
        self._audit(
            state,
            "H4_TRENDLINE_CONFIGURED_STRUCTURAL",
            bar,
            touches=len(anchors),
            quality=state.trendline.quality,
            anchor_1=older.time,
            anchor_2=newer.time,
            selection="LONG_SPAN_WELL_SPACED_CONTAINED",
        )

    def _update_trendline_break_state(self, state: H4StructureState, bar: dict[str, Any]) -> None:
        tl = state.trendline
        if tl.status == "UNAVAILABLE" or len(tl.anchors) < 2:
            return
        try:
            line_price = _line_price(tl.anchors[0], tl.anchors[-1], str(bar["time"]))
        except (ValueError, TypeError):
            return
        tl.last_line_price = line_price
        close = float(bar["close"])
        open_ = float(bar.get("open", close))
        breakout_dir = "BULLISH" if state.trend == "BEARISH" else "BEARISH"
        beyond = close > line_price if breakout_dir == "BULLISH" else close < line_price

        if tl.status == "ACTIVE" and beyond:
            tl.status = "BREAKOUT_PENDING"
            tl.breakout_time = str(bar["time"])
            tl.breakout_close = close
            self._audit(state, "H4_TRENDLINE_BREAK_CLOSED", bar, line_price=line_price, direction=breakout_dir, touches=tl.touch_count)
            return

        if tl.status == "BREAKOUT_PENDING":
            if str(bar["time"]) == tl.breakout_time:
                return
            directional_candle = close > open_ if breakout_dir == "BULLISH" else close < open_
            follow_through = close >= float(tl.breakout_close) if breakout_dir == "BULLISH" else close <= float(tl.breakout_close)
            if beyond and (directional_candle or follow_through):
                tl.status = "EARLY_DIRECTION_CONFIRMED"
                tl.confirmation_time = str(bar["time"])
                tl.early_direction = breakout_dir
                self._audit(
                    state,
                    "H4_TRENDLINE_REVERSAL_CONFIRMED",
                    bar,
                    line_price=line_price,
                    early_direction=breakout_dir,
                    touches=tl.touch_count,
                    quality=tl.quality,
                )
                # The broken line has completed its job. Preserve its anchors,
                # breakout/confirmation and early direction for audit/Supervisor,
                # but retire it from active structural projection immediately.
                tl.status = "RETIRED"
                tl.retired_time = str(bar["time"])
                self._audit(
                    state,
                    "H4_TRENDLINE_RETIRED_AFTER_CONFIRMATION",
                    bar,
                    early_direction=breakout_dir,
                )
            elif not beyond:
                tl.status = "ACTIVE"
                tl.breakout_time = None
                tl.breakout_close = None
                self._audit(state, "H4_TRENDLINE_FALSE_BREAK", bar, line_price=line_price)

    def _update_bullish(self, s: H4StructureState, b: dict[str, Any]) -> None:
        assert s.strategic_origin and s.strategic_endpoint and s.control_pivot
        if float(b["close"]) < s.control_pivot.price:
            s.phase = "BULLISH_REVERSAL_CANDIDATE"
            self._audit(s, "CONTROL_PIVOT_CLOSE_BREAK", b, control_pivot=s.control_pivot.price)
            return

        old_endpoint = s.strategic_endpoint.price
        if float(b["high"]) > old_endpoint:
            if s.correction_qualified:
                s.continuation_broken = True
                s.prior_endpoint = PricePoint(old_endpoint, s.strategic_endpoint.time)
            s.strategic_endpoint = PricePoint(float(b["high"]), str(b["time"]))
            s.phase = "BULLISH_CONTINUATION_FORMING" if s.correction_qualified else "BULLISH_IMPULSE"
            self._audit(s, "STRATEGIC_ENDPOINT_EXTENDED", b, endpoint=s.strategic_endpoint.price)
            return

        depth = (s.strategic_endpoint.price - float(b["low"])) / max(
            s.strategic_endpoint.price - s.strategic_origin.price, 1e-12
        )
        if depth <= 0:
            s.phase = "BULLISH_IMPULSE"
            return
        if s.correction_extreme is None or float(b["low"]) < s.correction_extreme.price:
            s.correction_extreme = PricePoint(float(b["low"]), str(b["time"]))
        s.correction_depth = max(s.correction_depth, depth)

        if s.correction_depth < FIB_MAJOR_THRESHOLD:
            s.phase = "BULLISH_IMPULSE"
            self._audit(s, "INTERNAL_PULLBACK_LT_38_2", b, depth=round(s.correction_depth, 6))
            return

        s.correction_qualified = True
        s.phase = "BULLISH_CORRECTION"
        self._audit(s, "STRATEGIC_CORRECTION_QUALIFIED", b, depth=round(s.correction_depth, 6))

        if s.continuation_broken and float(b["high"]) < s.strategic_endpoint.price and float(b["close"]) < s.strategic_endpoint.price:
            if s.correction_extreme:
                s.strategic_origin = s.correction_extreme
                s.control_pivot = s.correction_extreme
                s.correction_extreme = None
                s.correction_depth = 0.0
                s.correction_qualified = False
                s.continuation_broken = False
                s.prior_endpoint = None
                s.phase = "BULLISH_IMPULSE"
                self._audit(s, "STRATEGIC_ORIGIN_ROLLED_FORWARD", b, origin=s.strategic_origin.price)

    def _update_bearish(self, s: H4StructureState, b: dict[str, Any]) -> None:
        assert s.strategic_origin and s.strategic_endpoint and s.control_pivot
        if float(b["close"]) > s.control_pivot.price:
            s.phase = "BEARISH_REVERSAL_CANDIDATE"
            self._audit(s, "CONTROL_PIVOT_CLOSE_BREAK", b, control_pivot=s.control_pivot.price)
            return

        old_endpoint = s.strategic_endpoint.price
        if float(b["low"]) < old_endpoint:
            if s.correction_qualified:
                s.continuation_broken = True
                s.prior_endpoint = PricePoint(old_endpoint, s.strategic_endpoint.time)
            s.strategic_endpoint = PricePoint(float(b["low"]), str(b["time"]))
            s.phase = "BEARISH_CONTINUATION_FORMING" if s.correction_qualified else "BEARISH_IMPULSE"
            self._audit(s, "STRATEGIC_ENDPOINT_EXTENDED", b, endpoint=s.strategic_endpoint.price)
            return

        depth = (float(b["high"]) - s.strategic_endpoint.price) / max(
            s.strategic_origin.price - s.strategic_endpoint.price, 1e-12
        )
        if depth <= 0:
            s.phase = "BEARISH_IMPULSE"
            return
        if s.correction_extreme is None or float(b["high"]) > s.correction_extreme.price:
            s.correction_extreme = PricePoint(float(b["high"]), str(b["time"]))
        s.correction_depth = max(s.correction_depth, depth)

        if s.correction_depth < FIB_MAJOR_THRESHOLD:
            s.phase = "BEARISH_IMPULSE"
            self._audit(s, "INTERNAL_PULLBACK_LT_38_2", b, depth=round(s.correction_depth, 6))
            return

        s.correction_qualified = True
        s.phase = "BEARISH_CORRECTION"
        self._audit(s, "STRATEGIC_CORRECTION_QUALIFIED", b, depth=round(s.correction_depth, 6))

        if s.continuation_broken and float(b["low"]) > s.strategic_endpoint.price and float(b["close"]) > s.strategic_endpoint.price:
            if s.correction_extreme:
                s.strategic_origin = s.correction_extreme
                s.control_pivot = s.correction_extreme
                s.correction_extreme = None
                s.correction_depth = 0.0
                s.correction_qualified = False
                s.continuation_broken = False
                s.prior_endpoint = None
                s.phase = "BEARISH_IMPULSE"
                self._audit(s, "STRATEGIC_ORIGIN_ROLLED_FORWARD", b, origin=s.strategic_origin.price)


class H4StructureAgent(BaseAgent):
    agent_id = "H4_STRUCTURE"

    def __init__(self, store: InMemoryStateStore | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = H4StructureEngine()

    def seed(self, symbol: str, *, trend: str, origin: PricePoint, endpoint: PricePoint, control_pivot: PricePoint) -> None:
        state = self.engine.seed(trend=trend, origin=origin, endpoint=endpoint, control_pivot=control_pivot)
        self.store.set(self._key(symbol), state.to_dict())

    def configure_trendline(self, symbol: str, anchors: list[TrendlineAnchor]) -> None:
        raw = self.store.get(self._key(symbol))
        if raw is None:
            raise ValueError("H4_STATE_NOT_SEEDED")
        state = H4StructureState.from_dict(raw)
        self.engine.configure_trendline(state, anchors)
        self.store.set(self._key(symbol), state.to_dict())

    def _key(self, symbol: str) -> str:
        return f"structure:H4:{symbol}"

    def handle(self, event: Event) -> ReportEnvelope | None:
        if event.type != "H4_BAR_CLOSED":
            return None
        symbol = event.symbol or ""
        raw = self.store.get(self._key(symbol))
        if raw is None:
            return ReportEnvelope(self.agent_id, symbol, "H4", "WAIT", 0.0, {}, ["H4_STATE_NOT_SEEDED"])
        state = H4StructureState.from_dict(raw)
        state = self.engine.update(state, event.payload)
        self.store.set(self._key(symbol), state.to_dict())
        return ReportEnvelope(
            self.agent_id,
            symbol,
            "H4",
            "VALID",
            1.0,
            state.to_dict(),
            [state.last_reason_code],
            state_version=state.state_version,
        )
