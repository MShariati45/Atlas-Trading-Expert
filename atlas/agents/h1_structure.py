from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore
from atlas.core.structure_types import PricePoint

FIB_MAJOR_THRESHOLD = 0.382


@dataclass(slots=True)
class H1StructureState:
    """Pure H1 strategic structure state.

    Deliberately contains no H4 trend, H4 relationship, alignment permission,
    Fibonacci eligibility, or other cross-timeframe information.
    """
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
    reversal_direction: str = "NONE"
    reversal_origin: PricePoint | None = None
    reversal_endpoint: PricePoint | None = None
    reversal_correction_extreme: PricePoint | None = None
    reversal_correction_depth: float = 0.0
    reversal_correction_qualified: bool = False
    state_version: int = 0
    bars_processed: int = 0
    last_reason_code: str = "UNINITIALIZED"
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "H1StructureState":
        data = dict(raw)
        # Hard isolation: never hydrate legacy/cross-timeframe fields into H1.
        for key in list(data):
            if key.startswith("h4_") or key in {"h4", "alignment", "fib_eligible", "m15_eligible", "effective_direction", "trendline", "trendline_pivots", "recent_bars"}:
                data.pop(key, None)
        for name in ("strategic_origin", "strategic_endpoint", "control_pivot", "correction_extreme", "prior_endpoint", "reversal_origin", "reversal_endpoint", "reversal_correction_extreme"):
            if isinstance(data.get(name), dict):
                data[name] = PricePoint(**data[name])
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in allowed})


class H1StructureEngine:
    """Independent incremental H1 structure engine.

    It reads H1 bars only. No H4 state or direction can enter this engine.
    """

    def seed(self, *, trend: str, origin: PricePoint, endpoint: PricePoint, control_pivot: PricePoint) -> H1StructureState:
        if trend not in {"BULLISH", "BEARISH"}:
            raise ValueError("trend must be BULLISH or BEARISH")
        return H1StructureState(
            trend=trend,
            phase=f"{trend}_IMPULSE",
            strategic_origin=origin,
            strategic_endpoint=endpoint,
            control_pivot=control_pivot,
            state_version=1,
            last_reason_code="SEEDED_VALIDATED_H1_STRUCTURE",
        )

    def update(self, state: H1StructureState, bar: dict[str, Any]) -> H1StructureState:
        if state.trend == "UNINITIALIZED":
            return state
        for key in ("high", "low", "close", "time"):
            if key not in bar:
                raise ValueError(f"missing H1 bar field: {key}")
        if any(str(k).lower().startswith("h4") for k in bar):
            raise ValueError("H1_CROSS_TIMEFRAME_INPUT_FORBIDDEN")
        state.bars_processed += 1
        state.state_version += 1
        if state.trend == "BULLISH":
            self._update_bullish(state, bar)
        elif state.trend == "BEARISH":
            self._update_bearish(state, bar)
        return state

    def _audit(self, state: H1StructureState, code: str, bar: dict[str, Any], **extra: Any) -> None:
        state.last_reason_code = code
        state.audit.append({"time": bar["time"], "reason_code": code, **extra})
        state.audit = state.audit[-150:]

    def _clear_reversal(self, s: H1StructureState) -> None:
        s.reversal_direction = "NONE"
        s.reversal_origin = None
        s.reversal_endpoint = None
        s.reversal_correction_extreme = None
        s.reversal_correction_depth = 0.0
        s.reversal_correction_qualified = False

    def _start_reversal(self, s: H1StructureState, b: dict[str, Any], direction: str) -> None:
        assert s.strategic_endpoint
        s.reversal_direction = direction
        s.reversal_origin = PricePoint(s.strategic_endpoint.price, s.strategic_endpoint.time)
        if direction == "BEARISH":
            s.reversal_endpoint = PricePoint(float(b["low"]), str(b["time"]))
            s.phase = "BEARISH_REVERSAL_CANDIDATE"
        else:
            s.reversal_endpoint = PricePoint(float(b["high"]), str(b["time"]))
            s.phase = "BULLISH_REVERSAL_CANDIDATE"
        s.reversal_correction_extreme = None
        s.reversal_correction_depth = 0.0
        s.reversal_correction_qualified = False
        self._audit(s, "REVERSAL_CANDIDATE", b, direction=direction, origin=s.reversal_origin.price, endpoint=s.reversal_endpoint.price)

    def _confirm_reversal(self, s: H1StructureState, b: dict[str, Any]) -> None:
        assert s.reversal_direction in {"BULLISH", "BEARISH"}
        assert s.reversal_endpoint and s.reversal_correction_extreme
        new_trend = s.reversal_direction
        new_endpoint = PricePoint(s.reversal_endpoint.price, s.reversal_endpoint.time)
        new_control = PricePoint(s.reversal_correction_extreme.price, s.reversal_correction_extreme.time)
        s.trend = new_trend
        s.strategic_origin = new_control
        s.control_pivot = new_control
        s.strategic_endpoint = new_endpoint
        s.correction_extreme = None
        s.correction_depth = 0.0
        s.correction_qualified = False
        s.continuation_broken = False
        s.prior_endpoint = None
        s.phase = f"{new_trend}_IMPULSE"
        self._clear_reversal(s)
        self._audit(s, "NEW_TREND_CONFIRMED", b, trend=new_trend, origin=new_control.price, endpoint=new_endpoint.price)

    def _update_reversal_candidate(self, s: H1StructureState, b: dict[str, Any]) -> None:
        assert s.reversal_origin and s.reversal_endpoint
        if s.reversal_direction == "BEARISH":
            # A full recovery above the old bullish extreme invalidates the bearish transition.
            if float(b["close"]) > s.reversal_origin.price:
                self._clear_reversal(s)
                s.phase = "BULLISH_IMPULSE"
                if float(b["high"]) > s.strategic_endpoint.price:
                    s.strategic_endpoint = PricePoint(float(b["high"]), str(b["time"]))
                self._audit(s, "REVERSAL_CANDIDATE_INVALIDATED", b, restored_trend="BULLISH")
                return
            old_endpoint = s.reversal_endpoint.price
            if float(b["low"]) < old_endpoint:
                s.reversal_endpoint = PricePoint(float(b["low"]), str(b["time"]))
                if s.reversal_correction_qualified:
                    self._confirm_reversal(s, b)
                    return
                s.phase = "BEARISH_REVERSAL_CANDIDATE"
                self._audit(s, "REVERSAL_ENDPOINT_EXTENDED", b, direction="BEARISH", endpoint=s.reversal_endpoint.price)
                return
            depth = (float(b["high"]) - s.reversal_endpoint.price) / max(s.reversal_origin.price - s.reversal_endpoint.price, 1e-12)
            if depth > 0:
                if s.reversal_correction_extreme is None or float(b["high"]) > s.reversal_correction_extreme.price:
                    s.reversal_correction_extreme = PricePoint(float(b["high"]), str(b["time"]))
                s.reversal_correction_depth = max(s.reversal_correction_depth, depth)
            if s.reversal_correction_depth >= FIB_MAJOR_THRESHOLD:
                s.reversal_correction_qualified = True
                s.phase = "BEARISH_REVERSAL_CORRECTION_QUALIFIED"
                self._audit(s, "REVERSAL_CORRECTION_QUALIFIED", b, direction="BEARISH", depth=round(s.reversal_correction_depth, 6))
            else:
                s.phase = "BEARISH_REVERSAL_CANDIDATE"
                self._audit(s, "REVERSAL_INTERNAL_PULLBACK_LT_38_2", b, direction="BEARISH", depth=round(s.reversal_correction_depth, 6))
            return

        # Mirrored bullish transition after a bearish control-pivot break.
        if float(b["close"]) < s.reversal_origin.price:
            self._clear_reversal(s)
            s.phase = "BEARISH_IMPULSE"
            if float(b["low"]) < s.strategic_endpoint.price:
                s.strategic_endpoint = PricePoint(float(b["low"]), str(b["time"]))
            self._audit(s, "REVERSAL_CANDIDATE_INVALIDATED", b, restored_trend="BEARISH")
            return
        old_endpoint = s.reversal_endpoint.price
        if float(b["high"]) > old_endpoint:
            s.reversal_endpoint = PricePoint(float(b["high"]), str(b["time"]))
            if s.reversal_correction_qualified:
                self._confirm_reversal(s, b)
                return
            s.phase = "BULLISH_REVERSAL_CANDIDATE"
            self._audit(s, "REVERSAL_ENDPOINT_EXTENDED", b, direction="BULLISH", endpoint=s.reversal_endpoint.price)
            return
        depth = (s.reversal_endpoint.price - float(b["low"])) / max(s.reversal_endpoint.price - s.reversal_origin.price, 1e-12)
        if depth > 0:
            if s.reversal_correction_extreme is None or float(b["low"]) < s.reversal_correction_extreme.price:
                s.reversal_correction_extreme = PricePoint(float(b["low"]), str(b["time"]))
            s.reversal_correction_depth = max(s.reversal_correction_depth, depth)
        if s.reversal_correction_depth >= FIB_MAJOR_THRESHOLD:
            s.reversal_correction_qualified = True
            s.phase = "BULLISH_REVERSAL_CORRECTION_QUALIFIED"
            self._audit(s, "REVERSAL_CORRECTION_QUALIFIED", b, direction="BULLISH", depth=round(s.reversal_correction_depth, 6))
        else:
            s.phase = "BULLISH_REVERSAL_CANDIDATE"
            self._audit(s, "REVERSAL_INTERNAL_PULLBACK_LT_38_2", b, direction="BULLISH", depth=round(s.reversal_correction_depth, 6))

    def _roll_continuation_origin(self, s: H1StructureState, b: dict[str, Any], direction: str) -> None:
        assert s.correction_extreme
        s.prior_endpoint = PricePoint(s.strategic_endpoint.price, s.strategic_endpoint.time) if s.strategic_endpoint else None
        s.strategic_origin = PricePoint(s.correction_extreme.price, s.correction_extreme.time)
        s.control_pivot = PricePoint(s.correction_extreme.price, s.correction_extreme.time)
        s.correction_extreme = None
        s.correction_depth = 0.0
        s.correction_qualified = False
        s.continuation_broken = False
        s.phase = f"{direction}_IMPULSE"
        self._audit(s, "VALIDATED_BY_CONTINUATION_BOS", b, direction=direction, origin=s.strategic_origin.price)

    def _update_bullish(self, s: H1StructureState, b: dict[str, Any]) -> None:
        assert s.strategic_origin and s.strategic_endpoint and s.control_pivot
        if s.reversal_direction != "NONE":
            self._update_reversal_candidate(s, b)
            return
        if float(b["close"]) < s.control_pivot.price:
            s.phase = "BULLISH_REVERSAL_CANDIDATE"
            self._audit(s, "CONTROL_PIVOT_CLOSE_BREAK", b, control_pivot=s.control_pivot.price)
            self._start_reversal(s, b, "BEARISH")
            return
        old_endpoint = s.strategic_endpoint.price
        if float(b["high"]) > old_endpoint:
            had_qualified = s.correction_qualified and s.correction_extreme is not None
            s.strategic_endpoint = PricePoint(float(b["high"]), str(b["time"]))
            if had_qualified:
                self._roll_continuation_origin(s, b, "BULLISH")
            else:
                s.phase = "BULLISH_IMPULSE"
                self._audit(s, "STRATEGIC_ENDPOINT_EXTENDED", b, endpoint=s.strategic_endpoint.price)
            return
        depth = (s.strategic_endpoint.price - float(b["low"])) / max(s.strategic_endpoint.price - s.strategic_origin.price, 1e-12)
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

    def _update_bearish(self, s: H1StructureState, b: dict[str, Any]) -> None:
        assert s.strategic_origin and s.strategic_endpoint and s.control_pivot
        if s.reversal_direction != "NONE":
            self._update_reversal_candidate(s, b)
            return
        if float(b["close"]) > s.control_pivot.price:
            s.phase = "BEARISH_REVERSAL_CANDIDATE"
            self._audit(s, "CONTROL_PIVOT_CLOSE_BREAK", b, control_pivot=s.control_pivot.price)
            self._start_reversal(s, b, "BULLISH")
            return
        old_endpoint = s.strategic_endpoint.price
        if float(b["low"]) < old_endpoint:
            had_qualified = s.correction_qualified and s.correction_extreme is not None
            s.strategic_endpoint = PricePoint(float(b["low"]), str(b["time"]))
            if had_qualified:
                self._roll_continuation_origin(s, b, "BEARISH")
            else:
                s.phase = "BEARISH_IMPULSE"
                self._audit(s, "STRATEGIC_ENDPOINT_EXTENDED", b, endpoint=s.strategic_endpoint.price)
            return
        depth = (float(b["high"]) - s.strategic_endpoint.price) / max(s.strategic_origin.price - s.strategic_endpoint.price, 1e-12)
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


class H1StructureAgent(BaseAgent):
    agent_id = "H1_STRUCTURE"

    def __init__(self, store: InMemoryStateStore | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = H1StructureEngine()

    def _key(self, symbol: str) -> str:
        return f"structure:H1:{symbol}"

    def seed(self, symbol: str, *, trend: str, origin: PricePoint, endpoint: PricePoint, control_pivot: PricePoint) -> H1StructureState:
        state = self.engine.seed(trend=trend, origin=origin, endpoint=endpoint, control_pivot=control_pivot)
        self.store.set(self._key(symbol), state.to_dict())
        return state

    def handle(self, event: Event) -> ReportEnvelope | None:
        if event.type != "H1_BAR_CLOSED" or not event.symbol:
            return None
        forbidden = [k for k in event.payload if str(k).lower().startswith("h4")]
        if forbidden:
            return ReportEnvelope(self.agent_id, event.symbol, "H1", "REJECTED_INPUT", 0.0, {}, ["H1_CROSS_TIMEFRAME_INPUT_FORBIDDEN"])
        raw = self.store.get(self._key(event.symbol))
        if raw is None:
            return ReportEnvelope(self.agent_id, event.symbol, "H1", "WAITING_FOR_SEED", 0.0, {}, ["H1_STATE_NOT_INITIALIZED"])
        state = H1StructureState.from_dict(raw)
        state = self.engine.update(state, dict(event.payload))
        self.store.set(self._key(event.symbol), state.to_dict())
        return ReportEnvelope(self.agent_id, event.symbol, "H1", "VALID", 1.0, state.to_dict(), [state.last_reason_code], state_version=state.state_version)
