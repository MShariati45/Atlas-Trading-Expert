from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class AgentRoleContract:
    agent_id: str
    owns: frozenset[str]
    forbidden_inputs: frozenset[str]
    may_influence: frozenset[str]
    notes: str = ""

ROLE_CONTRACTS: dict[str, AgentRoleContract] = {
    "H4_STRUCTURE": AgentRoleContract(
        "H4_STRUCTURE",
        frozenset({"H4_TREND","H4_PIVOTS","H4_IMPULSE","H4_CONTROL_PIVOT","H4_TRENDLINE_EARLY_DIRECTION"}),
        frozenset({"H1_STATE","M15_REPORTS","SUPERVISOR_DECISION"}),
        frozenset({"COORDINATOR_CONTEXT"}),
        "H4 is computed from H4 bars only and never inherits H1 conclusions.",
    ),
    "H1_STRUCTURE": AgentRoleContract(
        "H1_STRUCTURE",
        frozenset({"H1_TREND","H1_PIVOTS","H1_IMPULSE","H1_CONTROL_PIVOT","H1_CORRECTION"}),
        frozenset({"H4_STATE","M15_REPORTS","SUPERVISOR_DECISION"}),
        frozenset({"FIBONACCI_CONTEXT","COORDINATOR_CONTEXT"}),
        "H1 is computed from H1 bars only and never inherits H4 conclusions.",
    ),
    "FIBONACCI": AgentRoleContract(
        "FIBONACCI",
        frozenset({"H1_RETRACEMENT_MEASUREMENT"}),
        frozenset({"H4_STATE","M15_PATTERN_STATE","TRADE_PERMISSION"}),
        frozenset({"DISPLAY_CONTEXT"}),
        "Fibonacci is informational in the v0.23.6 demo profile and cannot authorize an entry.",
    ),
    "M15_SPECIALISTS": AgentRoleContract(
        "M15_SPECIALISTS",
        frozenset({"OWN_PATTERN_GEOMETRY","OWN_TRIGGER","OWN_STRUCTURAL_STOP"}),
        frozenset({"OTHER_SPECIALIST_INTERNAL_STATE","FINAL_TRADE_DECISION","RISK_LEDGER"}),
        frozenset({"M15_COORDINATOR_REPORTS"}),
        "Specialists report independently; they do not call or mutate one another.",
    ),
    "M15_COORDINATOR": AgentRoleContract(
        "M15_COORDINATOR",
        frozenset({"DUPLICATE_DETECTION","CONFLICT_CLASSIFICATION","PRIMARY_TRIGGER_SELECTION"}),
        frozenset({"H4_MUTATION","H1_MUTATION","SPECIALIST_MUTATION","RISK_OVERRIDE"}),
        frozenset({"SUPERVISOR_PACKAGE"}),
        "Coordinator combines immutable specialist reports only.",
    ),
    "SUPERVISOR": AgentRoleContract(
        "SUPERVISOR",
        frozenset({"FINAL_GATES","DAILY_RISK_LEDGER","SESSION_NEWS_COST_STATIC_ZONE_DECISION"}),
        frozenset({"REWRITING_H4","REWRITING_H1","REWRITING_PATTERN_GEOMETRY","SELF_MODIFYING_STRATEGY"}),
        frozenset({"PAPER_OR_EXECUTION_PERMISSION","TRADE_MANAGEMENT"}),
        "Supervisor can approve/wait/reject but cannot rewrite upstream analytical state.",
    ),
    "RESEARCH_EDUCATION_SUPERVISOR": AgentRoleContract(
        "RESEARCH_EDUCATION_SUPERVISOR",
        frozenset({"TRUSTED_SOURCE_REGISTRY","LESSON_LIBRARY","CORRECTION_MEMORY","RESEARCH_PROPOSALS"}),
        frozenset({"LIVE_TRADE_PERMISSION","AUTOMATIC_RULE_MUTATION","UPSTREAM_STATE_MUTATION"}),
        frozenset({"OFF_HOURS_ADVISORY","VALIDATION_QUEUE"}),
        "Education is versioned and persistent, but never silently changes live trading rules.",
    ),
}
