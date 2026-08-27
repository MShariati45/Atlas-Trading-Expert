from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore


SUPPORTED_PATTERNS = {
    "ASCENDING_TRIANGLE",
    "DESCENDING_TRIANGLE",
    "SYMMETRICAL_TRIANGLE",
    "RISING_WEDGE",
    "FALLING_WEDGE",
}


@dataclass(slots=True)
class TriangleWedgePolicy:
    min_reaction_highs: int = 2
    min_reaction_lows: int = 2
    breakout_stale_after_bars: int = 3
    spread_multiplier: float = 1.5
    atr_fraction: float = 0.10
    wick_fraction: float = 0.50
    min_tick_multiple: float = 2.0


@dataclass(slots=True)
class TriangleWedgeState:
    permitted_direction: str = "NONE"
    fib_retracement_pct: float = 0.0
    pattern_state: str = "INACTIVE"
    pattern_type: str = "NONE"
    upper_boundary: float | None = None
    lower_boundary: float | None = None
    reaction_highs: int = 0
    reaction_lows: int = 0
    first_structural_sr: float | None = None
    first_structural_sr_type: str = "NONE"
    raw_stop_anchor: float | None = None
    breakout_time: str | None = None
    breakout_close: float | None = None
    structural_break_time: str | None = None
    entry_reference: float | None = None
    applied_buffer: float | None = None
    final_stop: float | None = None
    retest_state: str = "NONE"
    bars_since_trigger: int = 0
    state_version: int = 0
    last_reason_code: str = "UNINITIALIZED"
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TriangleWedgeState":
        return cls(**dict(raw))


class M15TriangleWedgeEngine:
    """M15 triangle/wedge specialist with Atlas-specific structural confirmation.

    Pattern-specific hard rule:
    1. A full M15 close outside the relevant pattern boundary is only a
       BOUNDARY_BREAK_CONFIRMED event.
    2. No entry candidate exists until price also closes beyond the first
       meaningful validated M15 resistance (long) or support (short) in the
       higher-timeframe permitted direction.
    3. A retest may improve context but is not mandatory.
    """

    def __init__(self, policy: TriangleWedgePolicy | None = None) -> None:
        self.policy = policy or TriangleWedgePolicy()

    def seed(self, *, permitted_direction: str, fib_retracement_pct: float) -> TriangleWedgeState:
        if permitted_direction not in {"LONG", "SHORT"}:
            raise ValueError("permitted_direction must be LONG or SHORT")
        active = fib_retracement_pct >= 38.2
        return TriangleWedgeState(
            permitted_direction=permitted_direction,
            fib_retracement_pct=fib_retracement_pct,
            pattern_state="SCANNING" if active else "INACTIVE",
            state_version=1,
            last_reason_code="BROAD_M15_LAYER_ACTIVE" if active else "WAITING_FOR_FIB_38_2",
        )

    def update_fib_context(self, state: TriangleWedgeState, retracement_pct: float, broad_active: bool | None = None) -> TriangleWedgeState:
        state.state_version += 1
        state.fib_retracement_pct = retracement_pct
        active = (retracement_pct >= 38.2) if broad_active is None else bool(broad_active)
        if active:
            if state.pattern_state == "INACTIVE":
                state.pattern_state = "SCANNING"
            self._audit(state, "BROAD_M15_LAYER_ACTIVE", {"time": "fib"}, retracement_pct=retracement_pct)
        elif state.pattern_state not in {"VALID_TRIGGER", "STALE", "INVALIDATED"}:
            state.pattern_state = "INACTIVE"
            self._audit(state, "WAITING_FOR_FIB_38_2", {"time": "fib"}, retracement_pct=retracement_pct)
        return state

    def register_pattern(self, state: TriangleWedgeState, info: dict[str, Any]) -> TriangleWedgeState:
        state.state_version += 1
        if state.pattern_state == "INACTIVE":
            state.last_reason_code = "TRIANGLE_WEDGE_DISCOVERY_BLOCKED_BY_FIB"
            return state
        required = ("pattern_type", "upper_boundary", "lower_boundary", "reaction_highs", "reaction_lows", "first_structural_sr")
        for key in required:
            if key not in info:
                raise ValueError(f"missing triangle/wedge field: {key}")

        pattern_type = str(info["pattern_type"]).upper()
        if pattern_type not in SUPPORTED_PATTERNS:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "UNSUPPORTED_TRIANGLE_WEDGE_TYPE"
            return state

        upper = float(info["upper_boundary"])
        lower = float(info["lower_boundary"])
        highs = int(info["reaction_highs"])
        lows = int(info["reaction_lows"])
        first_sr = float(info["first_structural_sr"])
        if lower >= upper:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "PATTERN_BOUNDARIES_INVALID"
            return state
        if highs < self.policy.min_reaction_highs or lows < self.policy.min_reaction_lows:
            state.pattern_state = "FORMING"
            state.last_reason_code = "INSUFFICIENT_MEANINGFUL_REACTION_PIVOTS"
            return state

        # The structural obstacle must be beyond the breakout boundary in the
        # permitted direction; otherwise it is not the first obstacle *after*
        # escaping the formation.
        if state.permitted_direction == "LONG" and first_sr <= upper:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "FIRST_RESISTANCE_NOT_BEYOND_UPPER_BOUNDARY"
            return state
        if state.permitted_direction == "SHORT" and first_sr >= lower:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "FIRST_SUPPORT_NOT_BEYOND_LOWER_BOUNDARY"
            return state

        state.pattern_type = pattern_type
        state.upper_boundary = upper
        state.lower_boundary = lower
        state.reaction_highs = highs
        state.reaction_lows = lows
        state.first_structural_sr = first_sr
        state.first_structural_sr_type = "RESISTANCE" if state.permitted_direction == "LONG" else "SUPPORT"
        state.raw_stop_anchor = float(info.get("stop_anchor", lower if state.permitted_direction == "LONG" else upper))
        state.pattern_state = "MATURE"
        state.last_reason_code = "TRIANGLE_WEDGE_MATURE"
        return state

    def update_bar(self, state: TriangleWedgeState, bar: dict[str, Any]) -> TriangleWedgeState:
        for key in ("close", "time"):
            if key not in bar:
                raise ValueError(f"missing M15 bar field: {key}")
        state.state_version += 1
        close = float(bar["close"])

        if state.pattern_state == "VALID_TRIGGER":
            state.bars_since_trigger += 1
            if state.bars_since_trigger > self.policy.breakout_stale_after_bars:
                state.pattern_state = "STALE"
                self._audit(state, "TRIANGLE_WEDGE_TRIGGER_STALE", bar)
            return state

        if state.pattern_state == "MATURE":
            if state.permitted_direction == "LONG" and state.upper_boundary is not None and close > state.upper_boundary:
                self._boundary_break(state, bar, close)
            elif state.permitted_direction == "SHORT" and state.lower_boundary is not None and close < state.lower_boundary:
                self._boundary_break(state, bar, close)
            return state

        if state.pattern_state == "WAITING_FOR_FIRST_SR_BREAK":
            # A confirmed boundary break that immediately closes back inside the
            # formation before clearing structure is treated as a failed break.
            if state.permitted_direction == "LONG" and state.upper_boundary is not None and close <= state.upper_boundary:
                state.pattern_state = "INVALIDATED"
                self._audit(state, "FALSE_BREAK_CLOSE_BACK_INSIDE_PATTERN", bar)
                return state
            if state.permitted_direction == "SHORT" and state.lower_boundary is not None and close >= state.lower_boundary:
                state.pattern_state = "INVALIDATED"
                self._audit(state, "FALSE_BREAK_CLOSE_BACK_INSIDE_PATTERN", bar)
                return state

            if self._sr_cleared(state, close):
                self._confirm_structural_break(state, bar, close)
            else:
                state.last_reason_code = "BREAKOUT_NOT_STRUCTURALLY_CONFIRMED"
            return state

        return state

    def register_retest(self, state: TriangleWedgeState, *, held: bool, time: str = "") -> TriangleWedgeState:
        state.state_version += 1
        if state.pattern_state not in {"WAITING_FOR_FIRST_SR_BREAK", "VALID_TRIGGER"}:
            return state
        state.retest_state = "CONFIRMED" if held else "FAILED"
        if not held and state.pattern_state != "VALID_TRIGGER":
            state.pattern_state = "INVALIDATED"
            self._audit(state, "PATTERN_RETEST_FAILED", {"time": time})
        else:
            self._audit(state, "PATTERN_RETEST_CONFIRMED", {"time": time})
        return state

    def _boundary_break(self, state: TriangleWedgeState, bar: dict[str, Any], close: float) -> None:
        state.breakout_time = str(bar["time"])
        state.breakout_close = close
        state.pattern_state = "WAITING_FOR_FIRST_SR_BREAK"
        self._audit(state, "BOUNDARY_BREAK_CONFIRMED", bar)
        # If one strong candle closes beyond both the geometric boundary and the
        # separately validated first structural obstacle, both hard gates have
        # objectively been satisfied on the same bar.
        if self._sr_cleared(state, close):
            self._confirm_structural_break(state, bar, close)

    def _sr_cleared(self, state: TriangleWedgeState, close: float) -> bool:
        if state.first_structural_sr is None:
            return False
        if state.permitted_direction == "LONG":
            return close > state.first_structural_sr
        return close < state.first_structural_sr

    def _confirm_structural_break(self, state: TriangleWedgeState, bar: dict[str, Any], close: float) -> None:
        state.pattern_state = "VALID_TRIGGER"
        state.structural_break_time = str(bar["time"])
        state.entry_reference = close
        state.applied_buffer = self._buffer(bar)
        state.bars_since_trigger = 0
        if state.raw_stop_anchor is None:
            state.raw_stop_anchor = state.lower_boundary if state.permitted_direction == "LONG" else state.upper_boundary
        assert state.raw_stop_anchor is not None
        if state.permitted_direction == "LONG":
            state.final_stop = state.raw_stop_anchor - state.applied_buffer
            self._audit(state, "BULL_TRIANGLE_WEDGE_STRUCTURAL_BREAK_VALID_TRIGGER", bar)
        else:
            state.final_stop = state.raw_stop_anchor + state.applied_buffer
            self._audit(state, "BEAR_TRIANGLE_WEDGE_STRUCTURAL_BREAK_VALID_TRIGGER", bar)

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
    def _audit(state: TriangleWedgeState, code: str, event: dict[str, Any], **extra: Any) -> None:
        state.last_reason_code = code
        state.audit.append({"time": str(event.get("time", "")), "reason_code": code, **extra})
        state.audit = state.audit[-100:]


class M15TriangleWedgeAgent(BaseAgent):
    agent_id = "M15_TRIANGLE_WEDGE"

    def __init__(self, store: InMemoryStateStore | None = None, policy: TriangleWedgePolicy | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = M15TriangleWedgeEngine(policy)

    def _key(self, symbol: str) -> str:
        return f"m15:triangle_wedge:{symbol}"

    def seed(self, symbol: str, *, permitted_direction: str, fib_retracement_pct: float) -> TriangleWedgeState:
        state = self.engine.seed(permitted_direction=permitted_direction, fib_retracement_pct=fib_retracement_pct)
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if not event.symbol:
            return None
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            if event.type in {"M15_BAR_CLOSED", "M15_TRIANGLE_WEDGE_CANDIDATE"}:
                return ReportEnvelope(self.agent_id, event.symbol, "M15", "WAITING_FOR_SEED", 0.0, {}, ["TRIANGLE_WEDGE_NOT_INITIALIZED"])
            return None

        state = TriangleWedgeState.from_dict(raw)
        if event.type == "FIB_CONTEXT_UPDATE":
            state = self.engine.update_fib_context(state, float(event.payload["retracement_pct"]), event.payload.get("broad_m15_activation"))
        elif event.type == "M15_TRIANGLE_WEDGE_CANDIDATE":
            state = self.engine.register_pattern(state, event.payload)
        elif event.type == "M15_TRIANGLE_WEDGE_RETEST":
            state = self.engine.register_retest(state, held=bool(event.payload["held"]), time=str(event.payload.get("time", "")))
        elif event.type == "M15_BAR_CLOSED":
            state = self.engine.update_bar(state, event.payload)
        else:
            return None

        self.store.set(self._key(event.symbol), state.to_dict())
        confidence = 0.94 if state.pattern_state == "VALID_TRIGGER" else (0.82 if state.pattern_state == "MATURE" else 0.58)
        return ReportEnvelope(
            self.agent_id,
            event.symbol,
            "M15",
            state.pattern_state,
            confidence,
            state.to_dict(),
            [state.last_reason_code],
            state_version=state.state_version,
        )


M15Agent = M15TriangleWedgeAgent
