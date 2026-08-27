from dataclasses import dataclass, field
from atlas.core.enums import Decision

@dataclass(slots=True)
class DecisionResult:
    decision: Decision
    reason_codes: list[str] = field(default_factory=list)

class SupervisorDecisionEngine:
    HARD_GATES = (
        "day_ok", "session_ok", "alignment_ok", "fib_ok", "m15_ok",
        "freshness_ok", "static_zone_ok", "spread_ok", "news_ok",
        "symbol_lock_ok", "daily_trade_limit_ok", "daily_risk_ok",
        "structural_stop_ok", "net_rr_ok",
    )

    def decide(self, gates: dict[str, bool | None]) -> DecisionResult:
        failed = [k for k in self.HARD_GATES if gates.get(k) is False]
        waiting = [k for k in self.HARD_GATES if gates.get(k) is None]
        if failed:
            return DecisionResult(Decision.REJECT, [f"GATE_FAILED:{k}" for k in failed])
        if waiting:
            return DecisionResult(Decision.WAIT, [f"GATE_PENDING:{k}" for k in waiting])
        return DecisionResult(Decision.APPROVE, ["ALL_HARD_GATES_PASSED"])
