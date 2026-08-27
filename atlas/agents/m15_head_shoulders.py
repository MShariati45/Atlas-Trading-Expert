from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore


SUPPORTED_PATTERNS = {"HEAD_SHOULDERS", "INVERSE_HEAD_SHOULDERS"}
ENTRY_MODELS = {"BREAKOUT", "CONFIRMATION_CANDLE", "RETEST"}


@dataclass(slots=True)
class HeadShouldersPolicy:
    shoulder_tolerance_atr: float = 0.75
    min_head_prominence_atr: float = 0.25
    max_breakout_distance_atr: float = 0.60
    stale_after_bars: int = 4
    spread_multiplier: float = 1.5
    atr_fraction: float = 0.10
    wick_fraction: float = 0.50
    min_tick_multiple: float = 2.0
    entry_model: str = "BREAKOUT"

    def __post_init__(self) -> None:
        self.entry_model = self.entry_model.upper()
        if self.entry_model not in ENTRY_MODELS:
            raise ValueError(f"entry_model must be one of {sorted(ENTRY_MODELS)}")


@dataclass(slots=True)
class HeadShouldersState:
    permitted_direction: str = "NONE"
    prior_trend: str = "UNINITIALIZED"
    fib_retracement_pct: float = 0.0
    pattern_type: str = "NONE"
    pattern_state: str = "SCANNING"
    left_shoulder: float | None = None
    head: float | None = None
    right_shoulder: float | None = None
    neckline: float | None = None
    neckline_slope: float = 0.0
    pattern_start_time: str | None = None
    pattern_end_time: str | None = None
    breakout_time: str | None = None
    breakout_close: float | None = None
    entry_model: str = "BREAKOUT"
    entry_reference: float | None = None
    raw_stop_anchor: float | None = None
    applied_buffer: float | None = None
    final_stop: float | None = None
    retest_pivot: float | None = None
    retest_state: str = "NONE"
    bars_since_breakout: int = 0
    state_version: int = 0
    last_reason_code: str = "UNINITIALIZED"
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HeadShouldersState":
        return cls(**dict(raw))


class M15HeadShouldersEngine:
    """M15 Head & Shoulders / Inverse Head & Shoulders specialist.

    Pattern-specific rules only:
    - prior trend is mandatory;
    - the head must be meaningfully beyond both shoulders;
    - shoulders may be asymmetric within a configurable ATR tolerance;
    - a decisive M15 close through the neckline confirms the pattern;
    - no Triangle/Wedge "next S/R break" rule is imported here;
    - entry timing is configurable for research/backtesting: breakout,
      confirmation-candle, or retest/rejection;
    - price that is already materially extended from the neckline is never chased.
    """

    def __init__(self, policy: HeadShouldersPolicy | None = None) -> None:
        self.policy = policy or HeadShouldersPolicy()

    def seed(self, *, permitted_direction: str, prior_trend: str, fib_retracement_pct: float) -> HeadShouldersState:
        if permitted_direction not in {"LONG", "SHORT"}:
            raise ValueError("permitted_direction must be LONG or SHORT")
        if prior_trend not in {"BULLISH", "BEARISH"}:
            raise ValueError("prior_trend must be BULLISH or BEARISH")
        state = HeadShouldersState(
            permitted_direction=permitted_direction,
            prior_trend=prior_trend,
            fib_retracement_pct=float(fib_retracement_pct),
            entry_model=self.policy.entry_model,
            state_version=1,
        )
        if fib_retracement_pct < 38.2:
            state.pattern_state = "INACTIVE"
            state.last_reason_code = "FIB_BELOW_38_2_HEAD_SHOULDERS_SLEEP"
        else:
            state.pattern_state = "SCANNING"
            state.last_reason_code = "HEAD_SHOULDERS_SCANNER_ACTIVE"
        return state

    def update_fib_context(self, state: HeadShouldersState, retracement_pct: float, broad_active: bool | None = None) -> HeadShouldersState:
        state.state_version += 1
        state.fib_retracement_pct = float(retracement_pct)
        if state.pattern_state in {"VALID_TRIGGER", "INVALIDATED", "STALE"}:
            return state
        active = (retracement_pct >= 38.2) if broad_active is None else bool(broad_active)
        if not active:
            state.pattern_state = "INACTIVE"
            state.last_reason_code = "FIB_BELOW_38_2_HEAD_SHOULDERS_SLEEP"
        elif state.pattern_state == "INACTIVE":
            state.pattern_state = "SCANNING"
            state.last_reason_code = "FIB_38_2_REACHED_HEAD_SHOULDERS_ACTIVE"
        return state

    def register_pattern(self, state: HeadShouldersState, info: dict[str, Any]) -> HeadShouldersState:
        state.state_version += 1
        if state.pattern_state == "INACTIVE":
            state.pattern_state = "INACTIVE"
            state.last_reason_code = "FIB_BELOW_38_2_HEAD_SHOULDERS_SLEEP"
            return state

        required = ("pattern_type", "left_shoulder", "head", "right_shoulder", "neckline", "atr")
        for key in required:
            if key not in info:
                raise ValueError(f"missing head/shoulders field: {key}")

        pattern_type = str(info["pattern_type"]).upper()
        if pattern_type not in SUPPORTED_PATTERNS:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "UNSUPPORTED_HEAD_SHOULDERS_TYPE"
            return state

        ls = float(info["left_shoulder"])
        head = float(info["head"])
        rs = float(info["right_shoulder"])
        neckline = float(info["neckline"])
        atr = max(float(info["atr"]), 1e-12)

        if abs(ls - rs) > self.policy.shoulder_tolerance_atr * atr:
            state.pattern_state = "INVALIDATED"
            state.last_reason_code = "SHOULDER_ASYMMETRY_EXCESSIVE"
            return state

        if pattern_type == "HEAD_SHOULDERS":
            if state.prior_trend != "BULLISH" or state.permitted_direction != "SHORT":
                state.pattern_state = "INVALIDATED"
                state.last_reason_code = "HEAD_SHOULDERS_CONTEXT_NOT_BEARISH_REVERSAL_ELIGIBLE"
                return state
            if head - max(ls, rs) < self.policy.min_head_prominence_atr * atr:
                state.pattern_state = "FORMING"
                state.last_reason_code = "HEAD_NOT_PROMINENT_ENOUGH"
                return state
            if neckline >= min(ls, rs):
                state.pattern_state = "INVALIDATED"
                state.last_reason_code = "HEAD_SHOULDERS_NECKLINE_GEOMETRY_INVALID"
                return state
        else:
            if state.prior_trend != "BEARISH" or state.permitted_direction != "LONG":
                state.pattern_state = "INVALIDATED"
                state.last_reason_code = "INVERSE_HEAD_SHOULDERS_CONTEXT_NOT_BULLISH_REVERSAL_ELIGIBLE"
                return state
            if min(ls, rs) - head < self.policy.min_head_prominence_atr * atr:
                state.pattern_state = "FORMING"
                state.last_reason_code = "INVERSE_HEAD_NOT_PROMINENT_ENOUGH"
                return state
            if neckline <= max(ls, rs):
                state.pattern_state = "INVALIDATED"
                state.last_reason_code = "INVERSE_HEAD_SHOULDERS_NECKLINE_GEOMETRY_INVALID"
                return state

        state.pattern_type = pattern_type
        state.left_shoulder = ls
        state.head = head
        state.right_shoulder = rs
        state.neckline = neckline
        state.neckline_slope = float(info.get("neckline_slope", 0.0))
        state.pattern_start_time = str(info.get("pattern_start_time", "")) or None
        state.pattern_end_time = str(info.get("pattern_end_time", "")) or None
        state.raw_stop_anchor = float(info.get("stop_anchor", rs))
        state.pattern_state = "MATURE"
        state.last_reason_code = f"{pattern_type}_MATURE"
        return state

    def update_bar(self, state: HeadShouldersState, bar: dict[str, Any]) -> HeadShouldersState:
        for key in ("close", "time", "atr"):
            if key not in bar:
                raise ValueError(f"missing M15 bar field: {key}")
        state.state_version += 1
        close = float(bar["close"])

        if state.pattern_state in {"VALID_TRIGGER", "INVALIDATED", "STALE", "INACTIVE", "SCANNING", "FORMING"}:
            if state.pattern_state == "VALID_TRIGGER":
                state.bars_since_breakout += 1
                if state.bars_since_breakout > self.policy.stale_after_bars:
                    state.pattern_state = "STALE"
                    self._audit(state, "HEAD_SHOULDERS_TRIGGER_STALE", bar)
            return state

        if state.pattern_state == "MATURE":
            if self._neckline_broken(state, close):
                self._on_neckline_break(state, bar)
            return state

        if state.pattern_state in {"WAITING_CONFIRMATION_CANDLE", "WAITING_RETEST"}:
            state.bars_since_breakout += 1
            if state.bars_since_breakout > self.policy.stale_after_bars:
                state.pattern_state = "STALE"
                self._audit(state, "HEAD_SHOULDERS_ENTRY_WINDOW_STALE", bar)
                return state

            if state.pattern_state == "WAITING_CONFIRMATION_CANDLE":
                if self._closed_back_inside(state, close):
                    state.pattern_state = "INVALIDATED"
                    self._audit(state, "HEAD_SHOULDERS_FALSE_BREAK_CLOSE_BACK_INSIDE_NECKLINE", bar)
                    return state
                if self._distance_from_neckline(state, close) <= self.policy.max_breakout_distance_atr * max(float(bar["atr"]), 1e-12):
                    self._make_trigger(state, bar, anchor=state.raw_stop_anchor, reason="HEAD_SHOULDERS_CONFIRMATION_CANDLE_VALID_TRIGGER")
                else:
                    state.pattern_state = "WAITING_RETEST"
                    self._audit(state, "CONFIRMATION_CANDLE_TOO_EXTENDED_WAIT_RETEST", bar)
            return state

        return state

    def register_retest(self, state: HeadShouldersState, info: dict[str, Any]) -> HeadShouldersState:
        state.state_version += 1
        if state.pattern_state not in {"WAITING_RETEST", "NECKLINE_BREAK_CONFIRMED"}:
            return state
        held = bool(info.get("held", False))
        rejected = bool(info.get("rejected", held))
        if not held or not rejected:
            state.retest_state = "FAILED"
            state.pattern_state = "INVALIDATED"
            self._audit(state, "HEAD_SHOULDERS_RETEST_FAILED", info)
            return state

        pivot = info.get("retest_pivot")
        if pivot is None:
            raise ValueError("retest_pivot required for confirmed H&S retest")
        state.retest_pivot = float(pivot)
        state.retest_state = "CONFIRMED"
        bar_like = {
            "time": str(info.get("time", "")),
            "close": float(info.get("entry_reference", info.get("close", state.neckline or 0.0))),
            "atr": float(info.get("atr", 0.0)),
            "spread": float(info.get("spread", 0.0)),
            "wick_stat": float(info.get("wick_stat", 0.0)),
            "tick_size": float(info.get("tick_size", 0.0)),
        }
        self._make_trigger(state, bar_like, anchor=state.retest_pivot, reason="HEAD_SHOULDERS_RETEST_REJECTION_VALID_TRIGGER")
        return state

    def _on_neckline_break(self, state: HeadShouldersState, bar: dict[str, Any]) -> None:
        close = float(bar["close"])
        atr = max(float(bar["atr"]), 1e-12)
        state.breakout_time = str(bar["time"])
        state.breakout_close = close
        state.bars_since_breakout = 0
        distance = self._distance_from_neckline(state, close)

        if distance > self.policy.max_breakout_distance_atr * atr:
            state.pattern_state = "WAITING_RETEST"
            self._audit(state, "NECKLINE_BREAK_CONFIRMED_BUT_ENTRY_TOO_EXTENDED_WAIT_RETEST", bar)
            return

        if state.entry_model == "BREAKOUT":
            self._make_trigger(state, bar, anchor=state.raw_stop_anchor, reason="HEAD_SHOULDERS_NECKLINE_BREAK_VALID_TRIGGER")
        elif state.entry_model == "CONFIRMATION_CANDLE":
            state.pattern_state = "WAITING_CONFIRMATION_CANDLE"
            self._audit(state, "NECKLINE_BREAK_CONFIRMED_WAIT_CONFIRMATION_CANDLE", bar)
        else:
            state.pattern_state = "WAITING_RETEST"
            self._audit(state, "NECKLINE_BREAK_CONFIRMED_WAIT_RETEST", bar)

    def _make_trigger(self, state: HeadShouldersState, bar: dict[str, Any], *, anchor: float | None, reason: str) -> None:
        if anchor is None:
            raise ValueError("structural stop anchor is required")
        state.pattern_state = "VALID_TRIGGER"
        state.entry_reference = float(bar["close"])
        state.bars_since_breakout = 0
        state.raw_stop_anchor = float(anchor)
        state.applied_buffer = self._buffer(bar)
        if state.permitted_direction == "SHORT":
            state.final_stop = state.raw_stop_anchor + state.applied_buffer
        else:
            state.final_stop = state.raw_stop_anchor - state.applied_buffer
        self._audit(state, reason, bar)

    @staticmethod
    def _neckline_broken(state: HeadShouldersState, close: float) -> bool:
        assert state.neckline is not None
        if state.pattern_type == "HEAD_SHOULDERS":
            return close < state.neckline
        return close > state.neckline

    @staticmethod
    def _closed_back_inside(state: HeadShouldersState, close: float) -> bool:
        assert state.neckline is not None
        if state.pattern_type == "HEAD_SHOULDERS":
            return close >= state.neckline
        return close <= state.neckline

    @staticmethod
    def _distance_from_neckline(state: HeadShouldersState, close: float) -> float:
        assert state.neckline is not None
        return abs(close - state.neckline)

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
    def _audit(state: HeadShouldersState, code: str, event: dict[str, Any], **extra: Any) -> None:
        state.last_reason_code = code
        state.audit.append({"time": str(event.get("time", "")), "reason_code": code, **extra})
        state.audit = state.audit[-100:]


class M15HeadShouldersAgent(BaseAgent):
    agent_id = "M15_HEAD_SHOULDERS"

    def __init__(self, store: InMemoryStateStore | None = None, policy: HeadShouldersPolicy | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = M15HeadShouldersEngine(policy)

    def _key(self, symbol: str) -> str:
        return f"m15:head_shoulders:{symbol}"

    def seed(self, symbol: str, *, permitted_direction: str, prior_trend: str, fib_retracement_pct: float) -> HeadShouldersState:
        state = self.engine.seed(
            permitted_direction=permitted_direction,
            prior_trend=prior_trend,
            fib_retracement_pct=fib_retracement_pct,
        )
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if not event.symbol:
            return None
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            if event.type in {"M15_BAR_CLOSED", "M15_HEAD_SHOULDERS_CANDIDATE"}:
                return ReportEnvelope(self.agent_id, event.symbol, "M15", "WAITING_FOR_SEED", 0.0, {}, ["HEAD_SHOULDERS_NOT_INITIALIZED"])
            return None

        state = HeadShouldersState.from_dict(raw)
        if event.type == "FIB_CONTEXT_UPDATE":
            state = self.engine.update_fib_context(state, float(event.payload["retracement_pct"]), event.payload.get("broad_m15_activation"))
        elif event.type == "M15_HEAD_SHOULDERS_CANDIDATE":
            state = self.engine.register_pattern(state, event.payload)
        elif event.type == "M15_HEAD_SHOULDERS_RETEST":
            state = self.engine.register_retest(state, event.payload)
        elif event.type == "M15_BAR_CLOSED":
            state = self.engine.update_bar(state, event.payload)
        else:
            return None

        self.store.set(self._key(event.symbol), state.to_dict())
        confidence = 0.95 if state.pattern_state == "VALID_TRIGGER" else (0.84 if state.pattern_state == "MATURE" else 0.60)
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


M15Agent = M15HeadShouldersAgent
