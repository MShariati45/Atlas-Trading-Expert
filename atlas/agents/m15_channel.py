from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore

SUPPORTED_CHANNELS = {"ASCENDING_CHANNEL", "DESCENDING_CHANNEL", "HORIZONTAL_CHANNEL"}

@dataclass(slots=True)
class ChannelPolicy:
    boundary_touch_tolerance_atr: float = 0.15
    min_reaction_highs: int = 2
    min_reaction_lows: int = 2
    max_parallel_deviation_ratio: float = 0.35
    stale_after_bars: int = 4
    spread_multiplier: float = 1.5
    atr_fraction: float = 0.10
    wick_fraction: float = 0.50
    min_tick_multiple: float = 2.0

@dataclass(slots=True)
class ChannelState:
    permitted_direction: str = "NONE"
    fib_retracement_pct: float = 0.0
    channel_type: str = "NONE"
    pattern_state: str = "SCANNING"
    upper_boundary: float | None = None
    lower_boundary: float | None = None
    reaction_highs: int = 0
    reaction_lows: int = 0
    upper_slope: float = 0.0
    lower_slope: float = 0.0
    parallel_deviation_ratio: float = 0.0
    boundary_rejection_time: str | None = None
    confirmation_time: str | None = None
    entry_reference: float | None = None
    raw_stop_anchor: float | None = None
    applied_buffer: float | None = None
    final_stop: float | None = None
    bars_since_trigger: int = 0
    state_version: int = 0
    last_reason_code: str = "UNINITIALIZED"
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChannelState":
        return cls(**dict(raw))

class M15ChannelEngine:
    """Pattern-specific M15 corrective-channel specialist."""

    def __init__(self, policy: ChannelPolicy | None = None) -> None:
        self.policy = policy or ChannelPolicy()

    def seed(self, *, permitted_direction: str, fib_retracement_pct: float) -> ChannelState:
        if permitted_direction not in {"LONG", "SHORT"}:
            raise ValueError("permitted_direction must be LONG or SHORT")
        s = ChannelState(permitted_direction=permitted_direction, fib_retracement_pct=float(fib_retracement_pct), state_version=1)
        if fib_retracement_pct < 38.2:
            s.pattern_state = "INACTIVE"
            s.last_reason_code = "FIB_BELOW_38_2_CHANNEL_SLEEP"
        else:
            s.last_reason_code = "CHANNEL_SCANNER_ACTIVE"
        return s

    def update_fib_context(self, state: ChannelState, retracement_pct: float, broad_active: bool | None = None) -> ChannelState:
        state.state_version += 1
        state.fib_retracement_pct = float(retracement_pct)
        if state.pattern_state in {"VALID_TRIGGER", "INVALIDATED", "STALE"}:
            return state
        active = (retracement_pct >= 38.2) if broad_active is None else bool(broad_active)
        if not active:
            state.pattern_state = "INACTIVE"
            state.last_reason_code = "FIB_BELOW_38_2_CHANNEL_SLEEP"
        elif state.pattern_state == "INACTIVE":
            state.pattern_state = "SCANNING"
            state.last_reason_code = "FIB_38_2_REACHED_CHANNEL_ACTIVE"
        return state

    def register_pattern(self, state: ChannelState, info: dict[str, Any]) -> ChannelState:
        state.state_version += 1
        if state.pattern_state == "INACTIVE":
            state.pattern_state = "INACTIVE"
            state.last_reason_code = "FIB_BELOW_38_2_CHANNEL_SLEEP"
            return state
        for key in ("channel_type", "upper_boundary", "lower_boundary", "reaction_highs", "reaction_lows"):
            if key not in info:
                raise ValueError(f"missing channel field: {key}")
        channel_type = str(info["channel_type"]).upper()
        if channel_type not in SUPPORTED_CHANNELS:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "UNSUPPORTED_CHANNEL_TYPE"
            return state
        upper = float(info["upper_boundary"])
        lower = float(info["lower_boundary"])
        highs = int(info["reaction_highs"])
        lows = int(info["reaction_lows"])
        upper_slope = float(info.get("upper_slope", 0.0))
        lower_slope = float(info.get("lower_slope", 0.0))
        if upper <= lower:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "CHANNEL_BOUNDARY_GEOMETRY_INVALID"
            return state
        if highs < self.policy.min_reaction_highs or lows < self.policy.min_reaction_lows:
            state.pattern_state = "FORMING"
            state.last_reason_code = "INSUFFICIENT_CHANNEL_REACTION_PIVOTS"
            return state
        denom = max(abs(upper_slope), abs(lower_slope), 1e-12)
        parallel_deviation = abs(upper_slope - lower_slope) / denom
        if channel_type != "HORIZONTAL_CHANNEL" and parallel_deviation > self.policy.max_parallel_deviation_ratio:
            state.pattern_state = "FORMING"
            state.last_reason_code = "CHANNEL_BOUNDARIES_NOT_PARALLEL_ENOUGH"
            return state
        if state.permitted_direction == "LONG" and channel_type != "DESCENDING_CHANNEL":
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "CHANNEL_NOT_CORRECTIVE_FOR_LONG_CONTEXT"
            return state
        if state.permitted_direction == "SHORT" and channel_type != "ASCENDING_CHANNEL":
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "CHANNEL_NOT_CORRECTIVE_FOR_SHORT_CONTEXT"
            return state
        state.channel_type = channel_type
        state.upper_boundary = upper
        state.lower_boundary = lower
        state.reaction_highs = highs
        state.reaction_lows = lows
        state.upper_slope = upper_slope
        state.lower_slope = lower_slope
        state.parallel_deviation_ratio = parallel_deviation
        state.raw_stop_anchor = float(info.get("stop_anchor", lower if state.permitted_direction == "LONG" else upper))
        state.pattern_state = "MATURE"
        state.last_reason_code = f"{channel_type}_MATURE"
        return state

    def update_bar(self, state: ChannelState, bar: dict[str, Any]) -> ChannelState:
        for key in ("close", "time", "atr"):
            if key not in bar:
                raise ValueError(f"missing M15 bar field: {key}")
        state.state_version += 1
        close = float(bar["close"])
        if state.pattern_state in {"INACTIVE", "SCANNING", "FORMING", "INVALIDATED", "STALE"}:
            return state
        if state.pattern_state == "VALID_TRIGGER":
            state.bars_since_trigger += 1
            if state.bars_since_trigger > self.policy.stale_after_bars:
                state.pattern_state = "STALE"
                self._audit(state, "CHANNEL_TRIGGER_STALE", bar)
            return state
        if state.pattern_state == "MATURE" and self._boundary_rejection(state, bar):
            state.boundary_rejection_time = str(bar["time"])
            low = float(bar.get("low", close))
            high = float(bar.get("high", close))
            if state.permitted_direction == "LONG":
                anchor = min(float(state.raw_stop_anchor if state.raw_stop_anchor is not None else low), low)
            else:
                anchor = max(float(state.raw_stop_anchor if state.raw_stop_anchor is not None else high), high)
            self._make_trigger(
                state, bar, anchor=anchor,
                reason="CHANNEL_BOUNDARY_REJECTION_VALID_TRIGGER", entry=close,
            )
        return state

    def _make_trigger(self, state: ChannelState, event: dict[str, Any], *, anchor: float | None, reason: str, entry: float | None = None) -> None:
        if anchor is None:
            raise ValueError("channel structural stop anchor is required")
        state.pattern_state = "VALID_TRIGGER"
        state.confirmation_time = str(event.get("time", "")) or state.confirmation_time
        state.entry_reference = float(entry if entry is not None else event["close"])
        state.bars_since_trigger = 0
        state.raw_stop_anchor = float(anchor)
        state.applied_buffer = self._buffer(event)
        state.final_stop = state.raw_stop_anchor - state.applied_buffer if state.permitted_direction == "LONG" else state.raw_stop_anchor + state.applied_buffer
        self._audit(state, reason, event)

    def _boundary_rejection(self, state: ChannelState, bar: dict[str, Any]) -> bool:
        if state.upper_boundary is None or state.lower_boundary is None:
            return False
        for key in ("open", "high", "low", "close", "atr"):
            if key not in bar:
                return False
        open_ = float(bar["open"]); high = float(bar["high"]); low = float(bar["low"]); close = float(bar["close"])
        atr = max(float(bar.get("atr", 0.0)), 0.0)
        tol = atr * self.policy.boundary_touch_tolerance_atr
        if state.permitted_direction == "LONG":
            touched = low <= float(state.lower_boundary) + tol
            rejected = close > open_ and close > float(state.lower_boundary)
            return touched and rejected
        touched = high >= float(state.upper_boundary) - tol
        rejected = close < open_ and close < float(state.upper_boundary)
        return touched and rejected

    def _buffer(self, b: dict[str, Any]) -> float:
        return max(
            max(float(b.get("spread", 0.0)), 0.0) * self.policy.spread_multiplier,
            max(float(b.get("atr", 0.0)), 0.0) * self.policy.atr_fraction,
            max(float(b.get("wick_stat", 0.0)), 0.0) * self.policy.wick_fraction,
            max(float(b.get("tick_size", 0.0)), 0.0) * self.policy.min_tick_multiple,
        )

    @staticmethod
    def _audit(state: ChannelState, code: str, event: dict[str, Any]) -> None:
        state.last_reason_code = code
        state.audit.append({"time": str(event.get("time", "")), "reason_code": code})
        state.audit = state.audit[-100:]

class M15ChannelAgent(BaseAgent):
    agent_id = "M15_CHANNEL"

    def __init__(self, store: InMemoryStateStore | None = None, policy: ChannelPolicy | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = M15ChannelEngine(policy)

    def _key(self, symbol: str) -> str:
        return f"m15:channel:{symbol}"

    def seed(self, symbol: str, *, permitted_direction: str, fib_retracement_pct: float) -> ChannelState:
        state = self.engine.seed(permitted_direction=permitted_direction, fib_retracement_pct=fib_retracement_pct)
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if not event.symbol:
            return None
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            if event.type in {"M15_BAR_CLOSED", "M15_CHANNEL_CANDIDATE"}:
                return ReportEnvelope(self.agent_id, event.symbol, "M15", "WAITING_FOR_SEED", 0.0, {}, ["CHANNEL_NOT_INITIALIZED"])
            return None
        state = ChannelState.from_dict(raw)
        if event.type == "FIB_CONTEXT_UPDATE":
            state = self.engine.update_fib_context(state, float(event.payload["retracement_pct"]), event.payload.get("broad_m15_activation"))
        elif event.type == "M15_CHANNEL_CANDIDATE":
            state = self.engine.register_pattern(state, event.payload)
        elif event.type == "M15_BAR_CLOSED":
            state = self.engine.update_bar(state, event.payload)
        else:
            return None
        self.store.set(self._key(event.symbol), state.to_dict())
        confidence = 0.94 if state.pattern_state == "VALID_TRIGGER" else (0.82 if state.pattern_state == "MATURE" else 0.58)
        return ReportEnvelope(self.agent_id, event.symbol, "M15", state.pattern_state, confidence, state.to_dict(), [state.last_reason_code], state_version=state.state_version)

M15Agent = M15ChannelAgent
