from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.structure_types import PricePoint
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore


@dataclass(slots=True)
class M15BufferPolicy:
    spread_multiplier: float = 1.5
    atr_fraction: float = 0.10
    wick_fraction: float = 0.50
    min_tick_multiple: float = 2.0
    meaningful_pullback_fraction: float = 0.382
    stale_after_bars: int = 3


@dataclass(slots=True)
class M15ImpulseCorrectionState:
    trend: str = "UNINITIALIZED"
    phase: str = "UNINITIALIZED"
    permitted_direction: str = "NONE"
    control_pivot: PricePoint | None = None
    structural_endpoint: PricePoint | None = None
    reversal_origin: PricePoint | None = None
    new_extreme: PricePoint | None = None
    candidate_reversal_pivot: PricePoint | None = None
    choch_time: str | None = None
    bos_time: str | None = None
    trigger_entry_reference: float | None = None
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
    def from_dict(cls, raw: dict[str, Any]) -> "M15ImpulseCorrectionState":
        data = dict(raw)
        for name in ("control_pivot", "structural_endpoint", "reversal_origin", "new_extreme", "candidate_reversal_pivot"):
            if isinstance(data.get(name), dict):
                data[name] = PricePoint(**data[name])
        return cls(**data)


class M15ImpulseCorrectionEngine:
    """Incremental M15 reversal/continuation structure tracker.

    The engine is intentionally stateful. It consumes an already validated M15
    structure and updates only from newly closed M15 bars. A CHoCH is never a
    trade trigger. Atlas must observe a new extreme, a meaningful pullback that
    creates the opposite control pivot (HL/LH), and then a BOS through that new
    extreme before emitting VALID_TRIGGER.
    """

    def __init__(self, policy: M15BufferPolicy | None = None) -> None:
        self.policy = policy or M15BufferPolicy()

    def seed(
        self,
        *,
        trend: str,
        control_pivot: PricePoint,
        endpoint: PricePoint,
        permitted_direction: str,
    ) -> M15ImpulseCorrectionState:
        if trend not in {"BULLISH", "BEARISH"}:
            raise ValueError("trend must be BULLISH or BEARISH")
        if permitted_direction not in {"LONG", "SHORT"}:
            raise ValueError("permitted_direction must be LONG or SHORT")
        return M15ImpulseCorrectionState(
            trend=trend,
            phase=f"{trend}_STRUCTURE_ACTIVE",
            permitted_direction=permitted_direction,
            control_pivot=control_pivot,
            structural_endpoint=endpoint,
            state_version=1,
            last_reason_code="SEEDED_VALIDATED_M15_STRUCTURE",
        )

    def update(self, state: M15ImpulseCorrectionState, bar: dict[str, Any]) -> M15ImpulseCorrectionState:
        for key in ("high", "low", "close", "time"):
            if key not in bar:
                raise ValueError(f"missing M15 bar field: {key}")
        state.state_version += 1

        if state.phase == "VALID_TRIGGER":
            state.bars_since_trigger += 1
            if state.bars_since_trigger > self.policy.stale_after_bars:
                state.phase = "STALE"
                self._audit(state, "TRIGGER_STALE", bar)
            return state
        if state.phase in {"STALE", "INVALIDATED"}:
            return state

        if state.trend == "BEARISH":
            self._update_bearish_to_bullish(state, bar)
        elif state.trend == "BULLISH":
            self._update_bullish_to_bearish(state, bar)
        return state

    def _audit(self, s: M15ImpulseCorrectionState, code: str, b: dict[str, Any], **extra: Any) -> None:
        s.last_reason_code = code
        s.audit.append({"time": str(b["time"]), "reason_code": code, **extra})
        s.audit = s.audit[-100:]

    def _update_bearish_to_bullish(self, s: M15ImpulseCorrectionState, b: dict[str, Any]) -> None:
        assert s.control_pivot and s.structural_endpoint
        high, low, close = float(b["high"]), float(b["low"]), float(b["close"])

        if s.phase == "BEARISH_STRUCTURE_ACTIVE":
            if low < s.structural_endpoint.price:
                s.structural_endpoint = PricePoint(low, str(b["time"]))
                self._audit(s, "BEARISH_ENDPOINT_EXTENDED", b, endpoint=low)
                return
            if close > s.control_pivot.price:
                if s.permitted_direction != "LONG":
                    s.phase = "INVALIDATED"
                    self._audit(s, "CHOCH_OPPOSITE_TO_HTF_PERMISSION", b)
                    return
                s.phase = "BULLISH_REVERSAL_CANDIDATE"
                s.choch_time = str(b["time"])
                s.reversal_origin = s.structural_endpoint
                s.new_extreme = PricePoint(high, str(b["time"]))
                self._audit(s, "BULLISH_CHOCH_CONFIRMED", b, broken_lh=s.control_pivot.price)
                return
            return

        if s.phase in {"BULLISH_REVERSAL_CANDIDATE", "BULLISH_PULLBACK_FORMING"}:
            assert s.reversal_origin and s.new_extreme

            if high > s.new_extreme.price and s.candidate_reversal_pivot is None:
                s.new_extreme = PricePoint(high, str(b["time"]))
                self._audit(s, "BULLISH_NEW_HH_EXTENDED", b, hh=high)

            leg = max(s.new_extreme.price - s.reversal_origin.price, 1e-12)
            retrace = (s.new_extreme.price - low) / leg

            if retrace >= self.policy.meaningful_pullback_fraction and low > s.reversal_origin.price:
                if s.candidate_reversal_pivot is None or low < s.candidate_reversal_pivot.price:
                    s.candidate_reversal_pivot = PricePoint(low, str(b["time"]))
                s.phase = "BULLISH_PULLBACK_FORMING"
                self._audit(s, "BULLISH_HL_CANDIDATE_FORMED", b, retrace=round(retrace, 6), hl=low)

            if s.candidate_reversal_pivot is not None and close > s.new_extreme.price:
                s.phase = "VALID_TRIGGER"
                s.trend = "BULLISH"
                s.bos_time = str(b["time"])
                s.trigger_entry_reference = close
                s.raw_stop_anchor = s.candidate_reversal_pivot.price
                s.applied_buffer = self._buffer(b)
                s.final_stop = s.raw_stop_anchor - s.applied_buffer
                s.bars_since_trigger = 0
                self._audit(
                    s,
                    "BULLISH_BOS_CONFIRMED_VALID_TRIGGER",
                    b,
                    entry=s.trigger_entry_reference,
                    stop=s.final_stop,
                    hl=s.raw_stop_anchor,
                )
                return

    def _update_bullish_to_bearish(self, s: M15ImpulseCorrectionState, b: dict[str, Any]) -> None:
        assert s.control_pivot and s.structural_endpoint
        high, low, close = float(b["high"]), float(b["low"]), float(b["close"])

        if s.phase == "BULLISH_STRUCTURE_ACTIVE":
            if high > s.structural_endpoint.price:
                s.structural_endpoint = PricePoint(high, str(b["time"]))
                self._audit(s, "BULLISH_ENDPOINT_EXTENDED", b, endpoint=high)
                return
            if close < s.control_pivot.price:
                if s.permitted_direction != "SHORT":
                    s.phase = "INVALIDATED"
                    self._audit(s, "CHOCH_OPPOSITE_TO_HTF_PERMISSION", b)
                    return
                s.phase = "BEARISH_REVERSAL_CANDIDATE"
                s.choch_time = str(b["time"])
                s.reversal_origin = s.structural_endpoint
                s.new_extreme = PricePoint(low, str(b["time"]))
                self._audit(s, "BEARISH_CHOCH_CONFIRMED", b, broken_hl=s.control_pivot.price)
                return
            return

        if s.phase in {"BEARISH_REVERSAL_CANDIDATE", "BEARISH_PULLBACK_FORMING"}:
            assert s.reversal_origin and s.new_extreme

            if low < s.new_extreme.price and s.candidate_reversal_pivot is None:
                s.new_extreme = PricePoint(low, str(b["time"]))
                self._audit(s, "BEARISH_NEW_LL_EXTENDED", b, ll=low)

            leg = max(s.reversal_origin.price - s.new_extreme.price, 1e-12)
            retrace = (high - s.new_extreme.price) / leg

            if retrace >= self.policy.meaningful_pullback_fraction and high < s.reversal_origin.price:
                if s.candidate_reversal_pivot is None or high > s.candidate_reversal_pivot.price:
                    s.candidate_reversal_pivot = PricePoint(high, str(b["time"]))
                s.phase = "BEARISH_PULLBACK_FORMING"
                self._audit(s, "BEARISH_LH_CANDIDATE_FORMED", b, retrace=round(retrace, 6), lh=high)

            if s.candidate_reversal_pivot is not None and close < s.new_extreme.price:
                s.phase = "VALID_TRIGGER"
                s.trend = "BEARISH"
                s.bos_time = str(b["time"])
                s.trigger_entry_reference = close
                s.raw_stop_anchor = s.candidate_reversal_pivot.price
                s.applied_buffer = self._buffer(b)
                s.final_stop = s.raw_stop_anchor + s.applied_buffer
                s.bars_since_trigger = 0
                self._audit(
                    s,
                    "BEARISH_BOS_CONFIRMED_VALID_TRIGGER",
                    b,
                    entry=s.trigger_entry_reference,
                    stop=s.final_stop,
                    lh=s.raw_stop_anchor,
                )
                return

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


class M15ImpulseCorrectionAgent(BaseAgent):
    agent_id = "M15_IMPULSE_CORRECTION"

    def __init__(self, store: InMemoryStateStore | None = None, policy: M15BufferPolicy | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = M15ImpulseCorrectionEngine(policy)

    def _key(self, symbol: str) -> str:
        return f"m15:impulse_correction:{symbol}"

    def seed(
        self,
        symbol: str,
        *,
        trend: str,
        control_pivot: PricePoint,
        endpoint: PricePoint,
        permitted_direction: str,
    ) -> M15ImpulseCorrectionState:
        state = self.engine.seed(
            trend=trend,
            control_pivot=control_pivot,
            endpoint=endpoint,
            permitted_direction=permitted_direction,
        )
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if event.type != "M15_BAR_CLOSED" or not event.symbol:
            return None
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            return ReportEnvelope(
                self.agent_id,
                event.symbol,
                "M15",
                "WAITING_FOR_SEED",
                0.0,
                {},
                ["M15_STRUCTURE_NOT_INITIALIZED"],
            )
        state = M15ImpulseCorrectionState.from_dict(raw)
        state = self.engine.update(state, event.payload)
        self.store.set(self._key(event.symbol), state.to_dict())
        status = "VALID_TRIGGER" if state.phase == "VALID_TRIGGER" else ("STALE" if state.phase == "STALE" else "VALID")
        return ReportEnvelope(
            self.agent_id,
            event.symbol,
            "M15",
            status,
            1.0 if state.phase == "VALID_TRIGGER" else 0.75,
            state.to_dict(),
            [state.last_reason_code],
            state_version=state.state_version,
        )


# Backward-compatible name used by the original skeleton.
M15Agent = M15ImpulseCorrectionAgent
