from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from atlas.agents.base import BaseAgent
from atlas.core.contracts import ReportEnvelope
from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore


@dataclass(slots=True)
class FibonacciState:
    direction: str = "NONE"
    origin_price: float = 0.0
    endpoint_price: float = 0.0
    current_price: float = 0.0
    retracement_pct: float = 0.0
    zone: str = "INACTIVE"
    state: str = "INACTIVE"
    flag_early_access: bool = False
    broad_m15_activation: bool = False
    new_flag_discovery_allowed: bool = False
    levels: dict[str, float] | None = None
    state_version: int = 0
    last_reason_code: str = "INACTIVE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FibonacciRetracementEngine:
    LEVELS = (0.236, 0.382, 0.5, 0.618, 0.786, 1.0)

    def calculate(
        self,
        *,
        direction: str,
        origin: float,
        endpoint: float,
        current: float,
        aligned: bool,
        correction_qualified: bool = False,
        max_correction_depth: float = 0.0,
    ) -> FibonacciState:
        if not aligned or direction not in {"BULLISH", "BEARISH"}:
            return FibonacciState(state="WAITING_FOR_ALIGNMENT", zone="INACTIVE", last_reason_code="HTF_ALIGNMENT_REQUIRED")
        span = abs(endpoint - origin)
        if span <= 0:
            return FibonacciState(state="WAITING_FOR_VALID_IMPULSE", zone="INACTIVE", last_reason_code="INVALID_IMPULSE_RANGE")

        if direction == "BULLISH":
            retr = max(0.0, (endpoint - current) / span)
            levels = {self._name(r): endpoint - span * r for r in self.LEVELS}
        else:
            retr = max(0.0, (current - endpoint) / span)
            levels = {self._name(r): endpoint + span * r for r in self.LEVELS}

        # Normalize floating-point noise so exact Fibonacci boundaries are
        # classified deterministically.  The H1 structure engine separately
        # retains the maximum correction depth reached during the active
        # strategic impulse.  That persistent H1 fact drives the latch.
        retr = round(retr, 12)
        max_depth = round(max(float(max_correction_depth), retr if correction_qualified else 0.0), 12)
        pct = retr * 100.0

        # Structure risk is persistent for the active H1 impulse once H1 has
        # reached 78.6% or current price is physically at/through 78.6%.
        if retr >= 0.786 or max_depth >= 0.786:
            state, zone, reason = "STRUCTURE_RISK", "FIB_78_6_PLUS", "EXTREME_CORRECTION_STRUCTURE_RISK"
            flag = False
            broad = False
            new_flag = False
        # Once H1 itself has qualified the correction at >=38.2%, broad M15
        # remains awake while price recovers toward the old endpoint.  The
        # latch resets naturally when H1 rolls to a new strategic impulse, at
        # which point correction_qualified/max_correction_depth reset.
        elif correction_qualified:
            flag = False
            broad = True
            new_flag = False
            if retr < 0.382:
                state, zone, reason = "ACTIVE_LATCHED_RECOVERY", "FIB_RECOVERY_AFTER_38_2", "BROAD_M15_LATCHED_AFTER_38_2"
            elif retr < 0.618:
                state, zone, reason = "ACTIVE_PRIMARY_CORRECTION", "FIB_38_2_TO_61_8", "BROAD_M15_ACTIVATED"
            else:
                state, zone, reason = "ACTIVE_DEEP_CORRECTION", "FIB_61_8_TO_78_6", "DEEP_CORRECTION"
        elif retr < 0.236:
            state, zone, reason = "ACTIVE_SHALLOW", "FIB_0_TO_23_6", "SHALLOW_CORRECTION"
            flag = True
            broad = False
            new_flag = True
        elif retr < 0.382:
            state, zone, reason = "ACTIVE_FLAG_ZONE", "FIB_23_6_TO_38_2", "FLAG_PENNANT_EARLY_ACCESS"
            flag = True
            broad = False
            new_flag = True
        elif retr < 0.618:
            state, zone, reason = "ACTIVE_PRIMARY_CORRECTION", "FIB_38_2_TO_61_8", "BROAD_M15_ACTIVATED"
            flag = False
            broad = True
            new_flag = False
        elif retr < 0.786:
            state, zone, reason = "ACTIVE_DEEP_CORRECTION", "FIB_61_8_TO_78_6", "DEEP_CORRECTION"
            flag = False
            broad = True
            new_flag = False
        else:
            raise AssertionError("unreachable fibonacci classification")

        return FibonacciState(
            direction=direction,
            origin_price=origin,
            endpoint_price=endpoint,
            current_price=current,
            retracement_pct=round(pct, 4),
            zone=zone,
            state=state,
            flag_early_access=flag,
            broad_m15_activation=broad,
            new_flag_discovery_allowed=new_flag,
            levels=levels,
            state_version=1,
            last_reason_code=reason,
        )

    @staticmethod
    def _name(r: float) -> str:
        return f"{r*100:.1f}".replace(".", "_")


class FibonacciAgent(BaseAgent):
    agent_id = "FIBONACCI"

    def __init__(self, store: InMemoryStateStore | None = None) -> None:
        self.store = store or InMemoryStateStore()
        self.engine = FibonacciRetracementEngine()

    def _key(self, symbol: str) -> str:
        return f"fib:{symbol}"

    def handle(self, event: Event) -> ReportEnvelope | None:
        if event.type not in {"HTF_ALIGNMENT_GAINED", "H1_STRUCTURE_UPDATED", "PRICE_UPDATE"} or not event.symbol:
            return None
        p = event.payload
        required = {"direction", "origin_price", "endpoint_price", "current_price", "aligned"}
        if not required.issubset(p):
            return ReportEnvelope(self.agent_id, event.symbol, "H1", "WAITING_FOR_INPUT", 0.0, {}, ["FIB_INPUT_INCOMPLETE"])
        state = self.engine.calculate(
            direction=str(p["direction"]),
            origin=float(p["origin_price"]),
            endpoint=float(p["endpoint_price"]),
            current=float(p["current_price"]),
            aligned=bool(p["aligned"]),
            correction_qualified=bool(p.get("correction_qualified", False)),
            max_correction_depth=float(p.get("max_correction_depth", p.get("correction_depth", 0.0))),
        )
        old = self.store.get(self._key(event.symbol))
        if old:
            state.state_version = int(old.get("state_version", 0)) + 1
        self.store.set(self._key(event.symbol), state.to_dict())
        return ReportEnvelope(
            self.agent_id,
            event.symbol,
            "H1",
            "VALID",
            1.0,
            state.to_dict(),
            [state.last_reason_code],
            state_version=state.state_version,
        )
