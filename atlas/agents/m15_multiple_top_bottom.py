from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore


@dataclass(slots=True)
class MultipleTopBottomPolicy:
    level_tolerance_atr: float = 0.25
    min_separation_bars: int = 2
    max_pattern_bars: int = 80
    stale_after_bars: int = 3
    spread_multiplier: float = 1.5
    atr_fraction: float = 0.10
    wick_fraction: float = 0.50
    min_tick_multiple: float = 2.0


@dataclass(slots=True)
class Pivot:
    kind: str
    price: float
    time: str
    bar_index: int


@dataclass(slots=True)
class MultipleTopBottomState:
    permitted_direction: str = "NONE"
    prior_trend: str = "UNINITIALIZED"
    pivots: list[dict[str, Any]] = field(default_factory=list)
    pattern_type: str = "NONE"
    pattern_state: str = "SCANNING"
    first_extreme: Pivot | None = None
    second_extreme: Pivot | None = None
    third_extreme: Pivot | None = None
    neckline: Pivot | None = None
    neckline_break_time: str | None = None
    entry_reference: float | None = None
    raw_stop_anchor: float | None = None
    applied_buffer: float | None = None
    final_stop: float | None = None
    bars_since_confirmation: int = 0
    state_version: int = 0
    last_reason_code: str = "UNINITIALIZED"
    notify_impulse_correction: bool = False
    structural_confirmation_status: str = "PENDING"
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MultipleTopBottomState":
        data = dict(raw)
        for name in ("first_extreme", "second_extreme", "third_extreme", "neckline"):
            if isinstance(data.get(name), dict):
                data[name] = Pivot(**data[name])
        return cls(**data)


class MultipleTopBottomEngine:
    """Stateful M15 double/triple top-bottom specialist.

    This engine intentionally separates pattern confirmation from later market-structure
    confirmation. A neckline close creates an EARLY_REVERSAL_CANDIDATE and asks the
    Impulse/Correction agent to re-evaluate independently; it never declares CHoCH/BOS
    on that agent's behalf.
    """

    def __init__(self, policy: MultipleTopBottomPolicy | None = None) -> None:
        self.policy = policy or MultipleTopBottomPolicy()

    def seed(self, *, permitted_direction: str, prior_trend: str) -> MultipleTopBottomState:
        if permitted_direction not in {"LONG", "SHORT"}:
            raise ValueError("permitted_direction must be LONG or SHORT")
        if prior_trend not in {"BULLISH", "BEARISH"}:
            raise ValueError("prior_trend must be BULLISH or BEARISH")
        return MultipleTopBottomState(
            permitted_direction=permitted_direction,
            prior_trend=prior_trend,
            state_version=1,
            last_reason_code="SEEDED_MULTIPLE_TOP_BOTTOM_SCANNER",
        )

    def register_pivot(self, state: MultipleTopBottomState, pivot: Pivot, market: dict[str, Any]) -> MultipleTopBottomState:
        state.state_version += 1
        if state.pattern_state in {"STALE", "INVALIDATED"}:
            return state
        state.pivots.append(asdict(pivot))
        state.pivots = state.pivots[-20:]
        self._evaluate_pattern(state, market)
        return state

    def update_bar(self, state: MultipleTopBottomState, bar: dict[str, Any]) -> MultipleTopBottomState:
        for key in ("close", "time"):
            if key not in bar:
                raise ValueError(f"missing M15 bar field: {key}")
        state.state_version += 1

        if state.pattern_state == "EARLY_REVERSAL_CANDIDATE":
            state.bars_since_confirmation += 1
            if state.bars_since_confirmation > self.policy.stale_after_bars:
                state.pattern_state = "STALE"
                self._audit(state, "MULTIPLE_TOP_BOTTOM_SIGNAL_STALE", bar)
                return state

        if state.pattern_state not in {"MATURE", "NECKLINE_BREAK_CONFIRMED", "EARLY_REVERSAL_CANDIDATE"}:
            return state
        if not state.neckline:
            return state

        close = float(bar["close"])
        if state.pattern_type in {"DOUBLE_BOTTOM", "TRIPLE_BOTTOM"}:
            if close > state.neckline.price and state.pattern_state == "MATURE":
                if state.permitted_direction != "LONG":
                    state.pattern_state = "INVALIDATED"
                    self._audit(state, "BOTTOM_BREAK_OPPOSITE_TO_HTF_PERMISSION", bar)
                    return state
                self._confirm(state, bar, direction="LONG")
            elif state.pattern_state == "EARLY_REVERSAL_CANDIDATE" and close < self._lowest_bottom(state):
                state.pattern_state = "INVALIDATED"
                self._audit(state, "BULLISH_PATTERN_BUSTED_BELOW_BOTTOMS", bar)
        elif state.pattern_type in {"DOUBLE_TOP", "TRIPLE_TOP"}:
            if close < state.neckline.price and state.pattern_state == "MATURE":
                if state.permitted_direction != "SHORT":
                    state.pattern_state = "INVALIDATED"
                    self._audit(state, "TOP_BREAK_OPPOSITE_TO_HTF_PERMISSION", bar)
                    return state
                self._confirm(state, bar, direction="SHORT")
            elif state.pattern_state == "EARLY_REVERSAL_CANDIDATE" and close > self._highest_top(state):
                state.pattern_state = "INVALIDATED"
                self._audit(state, "BEARISH_PATTERN_BUSTED_ABOVE_TOPS", bar)
        return state

    def _evaluate_pattern(self, s: MultipleTopBottomState, market: dict[str, Any]) -> None:
        pivots = [Pivot(**p) for p in s.pivots]
        if len(pivots) < 3:
            s.last_reason_code = "WAITING_FOR_PATTERN_PIVOTS"
            return
        atr = max(float(market.get("atr", 0.0)), 1e-12)
        tol = atr * self.policy.level_tolerance_atr

        # Bottom family: L-H-L or L-H-L-H-L
        if s.prior_trend == "BEARISH" and s.permitted_direction == "LONG":
            if len(pivots) >= 5:
                seq = pivots[-5:]
                if [p.kind for p in seq] == ["LOW", "HIGH", "LOW", "HIGH", "LOW"] and self._near(seq[0].price, seq[2].price, tol) and self._near(seq[0].price, seq[4].price, tol):
                    s.pattern_type = "TRIPLE_BOTTOM"
                    s.first_extreme, s.second_extreme, s.third_extreme = seq[0], seq[2], seq[4]
                    s.neckline = max((seq[1], seq[3]), key=lambda p: p.price)
                    s.pattern_state = "MATURE"
                    s.last_reason_code = "TRIPLE_BOTTOM_MATURE"
                    return
            seq = pivots[-3:]
            if [p.kind for p in seq] == ["LOW", "HIGH", "LOW"] and self._near(seq[0].price, seq[2].price, tol):
                if seq[2].bar_index - seq[0].bar_index >= self.policy.min_separation_bars:
                    s.pattern_type = "DOUBLE_BOTTOM"
                    s.first_extreme, s.second_extreme = seq[0], seq[2]
                    s.third_extreme = None
                    s.neckline = seq[1]
                    s.pattern_state = "MATURE"
                    s.last_reason_code = "DOUBLE_BOTTOM_MATURE"
                    return

        # Top family: H-L-H or H-L-H-L-H
        if s.prior_trend == "BULLISH" and s.permitted_direction == "SHORT":
            if len(pivots) >= 5:
                seq = pivots[-5:]
                if [p.kind for p in seq] == ["HIGH", "LOW", "HIGH", "LOW", "HIGH"] and self._near(seq[0].price, seq[2].price, tol) and self._near(seq[0].price, seq[4].price, tol):
                    s.pattern_type = "TRIPLE_TOP"
                    s.first_extreme, s.second_extreme, s.third_extreme = seq[0], seq[2], seq[4]
                    s.neckline = min((seq[1], seq[3]), key=lambda p: p.price)
                    s.pattern_state = "MATURE"
                    s.last_reason_code = "TRIPLE_TOP_MATURE"
                    return
            seq = pivots[-3:]
            if [p.kind for p in seq] == ["HIGH", "LOW", "HIGH"] and self._near(seq[0].price, seq[2].price, tol):
                if seq[2].bar_index - seq[0].bar_index >= self.policy.min_separation_bars:
                    s.pattern_type = "DOUBLE_TOP"
                    s.first_extreme, s.second_extreme = seq[0], seq[2]
                    s.third_extreme = None
                    s.neckline = seq[1]
                    s.pattern_state = "MATURE"
                    s.last_reason_code = "DOUBLE_TOP_MATURE"
                    return

        s.last_reason_code = "NO_VALID_MULTIPLE_TOP_BOTTOM_PATTERN"

    def _confirm(self, s: MultipleTopBottomState, bar: dict[str, Any], *, direction: str) -> None:
        close = float(bar["close"])
        s.pattern_state = "EARLY_REVERSAL_CANDIDATE"
        s.neckline_break_time = str(bar["time"])
        s.entry_reference = close
        s.notify_impulse_correction = True
        s.structural_confirmation_status = "PENDING"
        s.bars_since_confirmation = 0
        if direction == "LONG":
            s.raw_stop_anchor = self._lowest_bottom(s)
            s.applied_buffer = self._buffer(bar)
            s.final_stop = s.raw_stop_anchor - s.applied_buffer
            self._audit(s, "BULLISH_NECKLINE_BREAK_EARLY_REVERSAL_CANDIDATE", bar, neckline=s.neckline.price)
        else:
            s.raw_stop_anchor = self._highest_top(s)
            s.applied_buffer = self._buffer(bar)
            s.final_stop = s.raw_stop_anchor + s.applied_buffer
            self._audit(s, "BEARISH_NECKLINE_BREAK_EARLY_REVERSAL_CANDIDATE", bar, neckline=s.neckline.price)

    def apply_structure_confirmation(self, s: MultipleTopBottomState, status: str, time: str) -> None:
        if status not in {"CONFIRMED", "FAILED", "PENDING"}:
            raise ValueError("invalid structure confirmation status")
        s.structural_confirmation_status = status
        s.state_version += 1
        s.audit.append({"time": time, "reason_code": f"STRUCTURAL_CONFIRMATION_{status}"})
        s.audit = s.audit[-100:]

    def _buffer(self, b: dict[str, Any]) -> float:
        spread = max(float(b.get("spread", 0.0)), 0.0)
        atr = max(float(b.get("atr", 0.0)), 0.0)
        wick = max(float(b.get("wick_stat", 0.0)), 0.0)
        tick = max(float(b.get("tick_size", 0.0)), 0.0)
        return max(
            spread * self.policy.spread_multiplier,
            atr * self.policy.atr_fraction,
            wick * self.policy.wick_fraction,
            tick * self.policy.min_tick_multiple,
        )

    @staticmethod
    def _near(a: float, b: float, tol: float) -> bool:
        return abs(a - b) <= tol

    @staticmethod
    def _audit(s: MultipleTopBottomState, code: str, b: dict[str, Any], **extra: Any) -> None:
        s.last_reason_code = code
        s.audit.append({"time": str(b.get("time", "")), "reason_code": code, **extra})
        s.audit = s.audit[-100:]

    @staticmethod
    def _lowest_bottom(s: MultipleTopBottomState) -> float:
        points = [p.price for p in (s.first_extreme, s.second_extreme, s.third_extreme) if p is not None]
        return min(points)

    @staticmethod
    def _highest_top(s: MultipleTopBottomState) -> float:
        points = [p.price for p in (s.first_extreme, s.second_extreme, s.third_extreme) if p is not None]
        return max(points)


class M15MultipleTopBottomAgent(BaseAgent):
    agent_id = "M15_MULTIPLE_TOP_BOTTOM"

    def __init__(self, store: InMemoryStateStore | None = None, policy: MultipleTopBottomPolicy | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = MultipleTopBottomEngine(policy)

    def _key(self, symbol: str) -> str:
        return f"m15:multiple_top_bottom:{symbol}"

    def seed(self, symbol: str, *, permitted_direction: str, prior_trend: str) -> MultipleTopBottomState:
        state = self.engine.seed(permitted_direction=permitted_direction, prior_trend=prior_trend)
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if not event.symbol:
            return None
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            if event.type == "M15_BAR_CLOSED":
                return ReportEnvelope(self.agent_id, event.symbol, "M15", "WAITING_FOR_SEED", 0.0, {}, ["MULTIPLE_TOP_BOTTOM_NOT_INITIALIZED"])
            return None
        state = MultipleTopBottomState.from_dict(raw)
        if event.type == "M15_PIVOT_CONFIRMED":
            p = event.payload
            pivot = Pivot(str(p["kind"]), float(p["price"]), str(p["time"]), int(p["bar_index"]))
            state = self.engine.register_pivot(state, pivot, event.payload)
        elif event.type == "M15_BAR_CLOSED":
            state = self.engine.update_bar(state, event.payload)
        elif event.type == "M15_STRUCTURE_CONFIRMATION":
            self.engine.apply_structure_confirmation(state, str(event.payload["status"]), str(event.payload.get("time", "")))
        else:
            return None
        self.store.set(self._key(event.symbol), state.to_dict())
        status = "EARLY_REVERSAL_CANDIDATE" if state.pattern_state == "EARLY_REVERSAL_CANDIDATE" else state.pattern_state
        confidence = 0.90 if state.pattern_state == "EARLY_REVERSAL_CANDIDATE" else (0.75 if state.pattern_state == "MATURE" else 0.5)
        return ReportEnvelope(
            self.agent_id,
            event.symbol,
            "M15",
            status,
            confidence,
            state.to_dict(),
            [state.last_reason_code],
            state_version=state.state_version,
        )


M15Agent = M15MultipleTopBottomAgent
