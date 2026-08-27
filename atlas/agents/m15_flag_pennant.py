from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore


@dataclass(slots=True)
class FlagPennantPolicy:
    min_flagpole_atr: float = 2.0
    max_flagpole_bars: int = 12
    max_consolidation_bars: int = 12
    max_retracement_fraction: float = 0.382
    breakout_stale_after_bars: int = 3
    spread_multiplier: float = 1.5
    atr_fraction: float = 0.10
    wick_fraction: float = 0.50
    min_tick_multiple: float = 2.0


@dataclass(slots=True)
class FlagPennantState:
    permitted_direction: str = "NONE"
    fib_retracement_pct: float = 0.0
    discovery_allowed: bool = False
    pattern_state: str = "INACTIVE"
    pattern_type: str = "NONE"
    flagpole_origin: float | None = None
    flagpole_endpoint: float | None = None
    flagpole_size: float | None = None
    flagpole_atr_multiple: float | None = None
    flagpole_bars: int = 0
    consolidation_high: float | None = None
    consolidation_low: float | None = None
    consolidation_bars: int = 0
    consolidation_retracement_pct: float | None = None
    breakout_level: float | None = None
    breakout_time: str | None = None
    entry_reference: float | None = None
    raw_stop_anchor: float | None = None
    applied_buffer: float | None = None
    final_stop: float | None = None
    projected_flagpole_target: float | None = None
    bars_since_trigger: int = 0
    mature_carryover_allowed: bool = False
    state_version: int = 0
    last_reason_code: str = "UNINITIALIZED"
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FlagPennantState":
        return cls(**dict(raw))


class M15FlagPennantEngine:
    """Stateful flag/pennant continuation specialist.

    Atlas-specific activation rule:
    - New flag/pennant discovery is allowed only while the H1 Fibonacci correction
      remains below 38.2%.
    - If a pattern is already MATURE before 38.2% is crossed, it may continue to
      resolution instead of being discarded mechanically.
    - The pattern is continuation-only: the breakout must agree with the H4/H1
      permitted direction.
    """

    def __init__(self, policy: FlagPennantPolicy | None = None) -> None:
        self.policy = policy or FlagPennantPolicy()

    def seed(self, *, permitted_direction: str, fib_retracement_pct: float) -> FlagPennantState:
        if permitted_direction not in {"LONG", "SHORT"}:
            raise ValueError("permitted_direction must be LONG or SHORT")
        allowed = fib_retracement_pct < 38.2
        return FlagPennantState(
            permitted_direction=permitted_direction,
            fib_retracement_pct=fib_retracement_pct,
            discovery_allowed=allowed,
            pattern_state="SCANNING" if allowed else "INACTIVE",
            state_version=1,
            last_reason_code="FLAG_EARLY_ACCESS_ACTIVE" if allowed else "FIB_38_2_HANDOFF_NO_NEW_FLAG_DISCOVERY",
        )

    def update_fib_context(
        self, state: FlagPennantState, retracement_pct: float, new_discovery_allowed: bool | None = None
    ) -> FlagPennantState:
        state.state_version += 1
        state.fib_retracement_pct = retracement_pct
        allowed = (retracement_pct < 38.2) if new_discovery_allowed is None else bool(new_discovery_allowed)
        if allowed:
            state.discovery_allowed = True
            if state.pattern_state == "INACTIVE":
                state.pattern_state = "SCANNING"
            self._audit(state, "FLAG_EARLY_ACCESS_ACTIVE", {"time": "fib"}, retracement_pct=retracement_pct)
            return state

        state.discovery_allowed = False
        if state.pattern_state in {"MATURE", "BREAKOUT_CONFIRMED", "VALID_TRIGGER"}:
            state.mature_carryover_allowed = True
            self._audit(state, "MATURE_FLAG_CARRYOVER_AFTER_38_2", {"time": "fib"}, retracement_pct=retracement_pct)
        elif state.pattern_state in {"FLAGPOLE_VALID", "CONSOLIDATION_FORMING", "SCANNING"}:
            state.pattern_state = "INACTIVE"
            self._audit(state, "FIB_38_2_HANDOFF_NO_NEW_FLAG_DISCOVERY", {"time": "fib"}, retracement_pct=retracement_pct)
        return state

    def register_flagpole(self, state: FlagPennantState, pole: dict[str, Any]) -> FlagPennantState:
        state.state_version += 1
        if not state.discovery_allowed or state.pattern_state == "INACTIVE":
            state.last_reason_code = "NEW_FLAG_DISCOVERY_BLOCKED_BY_FIB"
            return state
        for key in ("origin", "endpoint", "bars", "atr"):
            if key not in pole:
                raise ValueError(f"missing flagpole field: {key}")
        origin = float(pole["origin"])
        endpoint = float(pole["endpoint"])
        bars = int(pole["bars"])
        atr = max(float(pole["atr"]), 1e-12)
        move = endpoint - origin
        direction = "LONG" if move > 0 else "SHORT"
        size = abs(move)
        atr_mult = size / atr

        if direction != state.permitted_direction:
            state.last_reason_code = "FLAGPOLE_OPPOSITE_TO_HTF_PERMISSION"
            return state
        if bars <= 0 or bars > self.policy.max_flagpole_bars:
            state.last_reason_code = "FLAGPOLE_DURATION_INVALID"
            return state
        if atr_mult < self.policy.min_flagpole_atr:
            state.last_reason_code = "FLAGPOLE_TOO_WEAK"
            return state

        state.flagpole_origin = origin
        state.flagpole_endpoint = endpoint
        state.flagpole_size = size
        state.flagpole_atr_multiple = atr_mult
        state.flagpole_bars = bars
        state.pattern_state = "FLAGPOLE_VALID"
        state.last_reason_code = "STRONG_FLAGPOLE_VALIDATED"
        return state

    def update_consolidation(self, state: FlagPennantState, info: dict[str, Any]) -> FlagPennantState:
        state.state_version += 1
        if state.pattern_state not in {"FLAGPOLE_VALID", "CONSOLIDATION_FORMING", "MATURE"}:
            return state
        if state.flagpole_size is None or state.flagpole_endpoint is None:
            return state
        for key in ("high", "low", "bars", "shape"):
            if key not in info:
                raise ValueError(f"missing consolidation field: {key}")
        high = float(info["high"])
        low = float(info["low"])
        bars = int(info["bars"])
        shape = str(info["shape"]).upper()
        if shape not in {"FLAG", "PENNANT"}:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "UNSUPPORTED_CONSOLIDATION_SHAPE"
            return state
        if bars <= 0 or bars > self.policy.max_consolidation_bars:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "CONSOLIDATION_TOO_LONG"
            return state

        if state.permitted_direction == "LONG":
            retr = max(0.0, (state.flagpole_endpoint - low) / state.flagpole_size)
            breakout_level = high
        else:
            retr = max(0.0, (high - state.flagpole_endpoint) / state.flagpole_size)
            breakout_level = low

        state.consolidation_high = high
        state.consolidation_low = low
        state.consolidation_bars = bars
        state.consolidation_retracement_pct = retr * 100.0
        state.pattern_type = f"{'BULL' if state.permitted_direction == 'LONG' else 'BEAR'}_{shape}"
        state.breakout_level = breakout_level

        if retr >= self.policy.max_retracement_fraction:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "FLAG_CONSOLIDATION_TOO_DEEP"
            return state

        state.pattern_state = "MATURE" if bars >= 2 else "CONSOLIDATION_FORMING"
        state.last_reason_code = "FLAG_PENNANT_MATURE" if state.pattern_state == "MATURE" else "CONSOLIDATION_FORMING"
        return state

    def update_bar(self, state: FlagPennantState, bar: dict[str, Any]) -> FlagPennantState:
        for key in ("close", "time"):
            if key not in bar:
                raise ValueError(f"missing M15 bar field: {key}")
        state.state_version += 1

        if state.pattern_state == "VALID_TRIGGER":
            state.bars_since_trigger += 1
            if state.bars_since_trigger > self.policy.breakout_stale_after_bars:
                state.pattern_state = "STALE"
                self._audit(state, "FLAG_TRIGGER_STALE", bar)
            return state
        if state.pattern_state != "MATURE" or state.breakout_level is None:
            return state

        close = float(bar["close"])
        if state.permitted_direction == "LONG" and close > state.breakout_level:
            self._confirm_breakout(state, bar, "LONG")
        elif state.permitted_direction == "SHORT" and close < state.breakout_level:
            self._confirm_breakout(state, bar, "SHORT")
        return state

    def _confirm_breakout(self, state: FlagPennantState, bar: dict[str, Any], direction: str) -> None:
        close = float(bar["close"])
        state.pattern_state = "VALID_TRIGGER"
        state.breakout_time = str(bar["time"])
        state.entry_reference = close
        state.applied_buffer = self._buffer(bar)
        state.bars_since_trigger = 0
        assert state.flagpole_size is not None
        if direction == "LONG":
            assert state.consolidation_low is not None
            state.raw_stop_anchor = state.consolidation_low
            state.final_stop = state.raw_stop_anchor - state.applied_buffer
            state.projected_flagpole_target = close + state.flagpole_size
            self._audit(state, "BULL_FLAG_PENNANT_BREAKOUT_VALID_TRIGGER", bar)
        else:
            assert state.consolidation_high is not None
            state.raw_stop_anchor = state.consolidation_high
            state.final_stop = state.raw_stop_anchor + state.applied_buffer
            state.projected_flagpole_target = close - state.flagpole_size
            self._audit(state, "BEAR_FLAG_PENNANT_BREAKOUT_VALID_TRIGGER", bar)

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
    def _audit(state: FlagPennantState, code: str, event: dict[str, Any], **extra: Any) -> None:
        state.last_reason_code = code
        state.audit.append({"time": str(event.get("time", "")), "reason_code": code, **extra})
        state.audit = state.audit[-100:]


class M15FlagPennantAgent(BaseAgent):
    agent_id = "M15_FLAG_PENNANT"

    def __init__(self, store: InMemoryStateStore | None = None, policy: FlagPennantPolicy | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = M15FlagPennantEngine(policy)

    def _key(self, symbol: str) -> str:
        return f"m15:flag_pennant:{symbol}"

    def seed(self, symbol: str, *, permitted_direction: str, fib_retracement_pct: float) -> FlagPennantState:
        state = self.engine.seed(permitted_direction=permitted_direction, fib_retracement_pct=fib_retracement_pct)
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if not event.symbol:
            return None
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            if event.type in {"M15_BAR_CLOSED", "M15_FLAGPOLE_CANDIDATE", "M15_CONSOLIDATION_UPDATE"}:
                return ReportEnvelope(self.agent_id, event.symbol, "M15", "WAITING_FOR_SEED", 0.0, {}, ["FLAG_PENNANT_NOT_INITIALIZED"])
            return None

        state = FlagPennantState.from_dict(raw)
        if event.type == "FIB_CONTEXT_UPDATE":
            state = self.engine.update_fib_context(
                state,
                float(event.payload["retracement_pct"]),
                event.payload.get("new_flag_discovery_allowed"),
            )
        elif event.type == "M15_FLAGPOLE_CANDIDATE":
            state = self.engine.register_flagpole(state, event.payload)
        elif event.type == "M15_CONSOLIDATION_UPDATE":
            state = self.engine.update_consolidation(state, event.payload)
        elif event.type == "M15_BAR_CLOSED":
            state = self.engine.update_bar(state, event.payload)
        else:
            return None

        self.store.set(self._key(event.symbol), state.to_dict())
        confidence = 0.92 if state.pattern_state == "VALID_TRIGGER" else (0.80 if state.pattern_state == "MATURE" else 0.55)
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


M15Agent = M15FlagPennantAgent
