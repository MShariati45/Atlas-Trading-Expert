from atlas.supervisor.decision_engine import SupervisorDecisionEngine
from atlas.core.enums import Decision

def test_rejects_failed_gate():
    engine = SupervisorDecisionEngine()
    gates = {g: True for g in engine.HARD_GATES}
    gates["static_zone_ok"] = False
    result = engine.decide(gates)
    assert result.decision is Decision.REJECT

def test_waits_pending_gate():
    engine = SupervisorDecisionEngine()
    gates = {g: True for g in engine.HARD_GATES}
    gates["news_ok"] = None
    result = engine.decide(gates)
    assert result.decision is Decision.WAIT

def test_approves_all_passed():
    engine = SupervisorDecisionEngine()
    gates = {g: True for g in engine.HARD_GATES}
    result = engine.decide(gates)
    assert result.decision is Decision.APPROVE
