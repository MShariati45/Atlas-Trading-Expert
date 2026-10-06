"""Atlas project overlay: A/B/C classification, research gates, execution boundary, approval routing.

The development workflow never promotes strategies and never activates Demo/Live. Code merge is not
activation, and a development task reaching DONE is not strategy promotion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .contracts import BLOCKER_FLAGS, ENGINEERING_AREAS, EVIDENCE_AREAS, OWNER_SENSITIVE, TaskContract

POLICY_VERSION = "atlas-devwf.policy.v1"
PROTECTED_BRANCHES = frozenset({"main", "master"})

C_AREAS = frozenset({"risk_sizing", "portfolio_allocation", "execution_transport", "demo_activation",
                     "production_live", "credentials", "destructive_schema"})
B_AREAS = (OWNER_SENSITIVE - C_AREAS) | EVIDENCE_AREAS
EXPERIMENT_AREAS = frozenset({"strategy_logic", "H4_last_impulse_semantics", "entry_stop_target_management",
                              "cost_outcome_model", "holdout_evaluator_rules", "labels_ground_truth"})
ACTIVATION_STAGES = frozenset({"demo_activation", "limited_live", "real_money"})

LEGACY_PREFIX = "atlas/"
_B_PATH_PREFIXES = ("atlas2/evaluate", "atlas2/labels", "atlas2/research", "atlas2/detect", "atlas2/data",
                    "atlas2/replay", "atlas2/strategy", "atlas2/legacy_import", "atlas2/store/schema")
_C_PATH_RE = re.compile(r"(^|/|_)(execution|transport|broker|order|mt5_demo|live|risk|credential)", re.I)

# Executable evidence QA must report (true) before a change can pass TESTING.
_CHECKS_BY_AREA: dict[str, tuple[str, ...]] = {
    "strategy_logic": ("causal_no_lookahead", "baseline_retained", "replay_determinism"),
    "H4_last_impulse_semantics": ("causal_no_lookahead", "baseline_retained", "human_h4_authority_preserved"),
    "entry_stop_target_management": ("baseline_retained", "paired_baseline_challenger", "cost_realism"),
    "cost_outcome_model": ("baseline_retained", "cost_realism"),
    "holdout_evaluator_rules": ("holdout_guard", "baseline_retained"),
    "labels_ground_truth": ("retrospective_label_taint",),
    "taint_causality": ("taint_propagation", "causal_no_lookahead"),
    "macro_availability": ("pit_availability", "non_pit_taint", "taint_propagation"),
    "detector_capture": ("candidate_capture_before_gates", "rejected_candidates_retained"),
    "evidence_data": ("replay_determinism", "append_only_evidence"),
    "replay_identity": ("replay_determinism", "content_identity"),
    "risk_sizing": ("no_order_path", "no_live_activation", "fail_closed_default"),
    "portfolio_allocation": ("no_live_activation", "fail_closed_default"),
    "execution_transport": ("no_live_activation", "fail_closed_default", "no_real_money_path"),
    "demo_activation": ("no_live_activation",),
    "production_live": ("no_live_activation",),
    "credentials": ("no_secret_in_evidence",),
    "destructive_schema": ("migration_reversible",),
}


@dataclass(frozen=True)
class Block:
    code: str
    reason: str
    recoverable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "reason": self.reason, "recoverable": self.recoverable}


@dataclass(frozen=True)
class Classification:
    task_class: str
    impact_areas: tuple[str, ...]
    owner_sensitive: tuple[str, ...]
    reasons: tuple[str, ...]
    legacy_touch: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"task_class": self.task_class, "impact_areas": list(self.impact_areas),
                "owner_sensitive": list(self.owner_sensitive), "reasons": list(self.reasons),
                "legacy_touch": self.legacy_touch, "policy_version": POLICY_VERSION}


@dataclass(frozen=True)
class QAOutcome:
    passed: bool
    missing_checks: tuple[str, ...] = ()
    failed_checks: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def _max_class(*classes: str) -> str:
    return max(classes)  # "A" < "B" < "C"


def _path_class(path: str) -> tuple[str, str | None]:
    if path == "atlas" or path.startswith(LEGACY_PREFIX):
        return "C", f"legacy path {path}"
    if _C_PATH_RE.search(path):
        return "C", f"risk/execution path {path}"
    if any(path == p or path.startswith(p + "/") or path.startswith(p) for p in _B_PATH_PREFIXES):
        return "B", f"evidence/evaluator path {path}"
    return "A", None


def classify(contract: TaskContract, *, extra_areas: Iterable[str] = (), extra_paths: Iterable[str] = ()) -> Classification:
    """Derive the effective class. The declared class is a floor: classification never downgrades."""
    areas = tuple(sorted(set(contract.impact_areas) | set(extra_areas)))
    reasons = [f"declared {contract.declared_class}"]
    klass = contract.declared_class
    for area in areas:
        if area in C_AREAS:
            klass = _max_class(klass, "C")
            reasons.append(f"area {area} -> C")
        elif area in B_AREAS:
            klass = _max_class(klass, "B")
            reasons.append(f"area {area} -> B")
    legacy = False
    for path in tuple(contract.scope_paths) + tuple(extra_paths):
        path_class, why = _path_class(path)
        if why:
            reasons.append(f"{why} -> {path_class}")
            klass = _max_class(klass, path_class)
        legacy = legacy or path == "atlas" or path.startswith(LEGACY_PREFIX)
    if contract.execution_stage in ACTIVATION_STAGES | {"demo_code"}:
        klass = _max_class(klass, "C")
        reasons.append(f"execution_stage {contract.execution_stage} -> C")
    sensitive = tuple(sorted(set(areas) & OWNER_SENSITIVE))
    return Classification(klass, areas, sensitive, tuple(reasons), legacy)


def experiment_required(classification: Classification) -> bool:
    return classification.task_class in ("B", "C") and bool(set(classification.impact_areas) & EXPERIMENT_AREAS)


def required_checks(classification: Classification, contract: TaskContract) -> tuple[str, ...]:
    checks = {"unit_tests"}
    if classification.task_class in ("B", "C"):
        checks.add("taint_propagation")
        checks.add("replay_determinism")
    for area in classification.impact_areas:
        checks.update(_CHECKS_BY_AREA.get(area, ()))
    if contract.experiment is not None or (contract.holdout_access and contract.holdout_access.requested):
        checks.update({"holdout_guard", "baseline_retained"})
    if classification.task_class == "C":
        checks.update({"no_live_activation", "fail_closed_default"})
        if contract.execution_stage != "demo_code":
            checks.add("no_order_path")
        else:
            checks.add("no_real_money_path")
    return tuple(sorted(checks))


def intake_blocks(contract: TaskContract, classification: Classification) -> list[Block]:
    """Fail-closed intake gate. Any block here prevents all agent invocation."""
    blocks: list[Block] = []
    if contract.activation_allowed:
        blocks.append(Block("ACTIVATION_FORBIDDEN",
                            "activation_allowed=true is always rejected; merge is not activation"))
    if contract.execution_stage in ACTIVATION_STAGES:
        blocks.append(Block("SEPARATE_OWNER_AUTHORIZATION_REQUIRED",
                            f"execution_stage={contract.execution_stage} is outside the development workflow; "
                            "route to separate owner authorization (OwnerLiveApproval + host-local token)"))
    if contract.work_branch in PROTECTED_BRANCHES:
        blocks.append(Block("DIRECT_MAIN_FORBIDDEN", f"work branch {contract.work_branch} is protected"))
    if classification.legacy_touch and not contract.legacy_mutation_authorized:
        blocks.append(Block("LEGACY_MUTATION_UNAUTHORIZED",
                            "atlas/ legacy is protected; mutation needs explicit contract authorization"))
    if classification.legacy_touch and classification.task_class != "C":
        blocks.append(Block("LEGACY_REQUIRES_CLASS_C", "legacy mutation must use the Class C risk path"))
    holdout = contract.holdout_access
    if holdout and holdout.requested:
        if not holdout.via_preregistered_path or not holdout.grant_id or contract.experiment is None:
            blocks.append(Block("HOLDOUT_ACCESS_DENIED",
                                "holdout exposure requires a preregistered experiment path and a grant"))
        if not holdout.instrument_intervals:
            blocks.append(Block("HOLDOUT_ACCESS_DENIED", "holdout grant must name instrument x time intervals"))
    exp = contract.experiment
    if experiment_required(classification) and exp is None:
        blocks.append(Block("EXPERIMENT_REQUIRED",
                            "semantic research change requires experiment ID, preregistration, baseline/challenger"))
    if exp is not None:
        if exp.evaluator_changed_after_protected_results:
            blocks.append(Block("CONFIRMATORY_INVALID_NEW_EXPERIMENT_REQUIRED",
                                "evaluator/scoring changed after protected results; register a new experiment"))
        if (exp.confirmatory or (holdout and holdout.requested)) and not exp.evaluator_frozen:
            blocks.append(Block("EVALUATOR_NOT_FROZEN", "evaluator must be frozen before protected exposure"))
        if exp.baseline.strip() == exp.challenger.strip():
            blocks.append(Block("BASELINE_CHALLENGER_IDENTICAL", "challenger must be compared against a retained baseline"))
        if not exp.failed_result_persistence:
            blocks.append(Block("FAILED_RESULT_PERSISTENCE_REQUIRED", "failed/inconclusive results must persist"))
    return blocks


def plan_blocks(contract: TaskContract, classification: Classification, plan: Mapping[str, Any]) -> tuple[Classification, list[Block]]:
    """Re-classify with plan-discovered impact and check plan obligations."""
    extra = [a for a in plan["impact_areas"] if a not in ENGINEERING_AREAS]
    updated = classify(contract, extra_areas=extra)
    if plan["proposed_class"] > updated.task_class:
        updated = Classification(plan["proposed_class"], updated.impact_areas, updated.owner_sensitive,
                                 updated.reasons + (f"planner proposed {plan['proposed_class']}",), updated.legacy_touch)
    blocks = []
    if updated.task_class != classification.task_class or updated.owner_sensitive != classification.owner_sensitive:
        blocks.extend(intake_blocks(contract, updated))
    if plan.get("experiment_required") and contract.experiment is None:
        blocks.append(Block("EXPERIMENT_REQUIRED", "planner identified an experiment requirement"))
    if (contract.experiment is not None or experiment_required(updated)) and plan.get("baseline_retained") is not True:
        blocks.append(Block("BASELINE_NOT_RETAINED", "plan must retain the baseline as a comparison arm"))
    if plan.get("legacy_touch") and not contract.legacy_mutation_authorized:
        blocks.append(Block("LEGACY_MUTATION_UNAUTHORIZED", "plan touches legacy atlas/ without authorization"))
    if updated.task_class == "A" and plan["semantics_change"]:
        blocks.append(Block("SEMANTICS_CHANGE_IN_CLASS_A", "Class A task cannot change trading/research semantics"))
    return updated, _dedupe(blocks)


def _in_scope(path: str, scope: Iterable[str]) -> bool:
    return any(path == s or path.startswith(s.rstrip("/") + "/") for s in scope)


def implementation_blocks(contract: TaskContract, classification: Classification, payload: Mapping[str, Any]) -> list[Block]:
    b = payload["boundary"]
    blocks = []
    if b["activates_demo"] or b["activates_live"]:
        blocks.append(Block("ACTIVATION_FORBIDDEN", "implementation attempted Demo/Live activation"))
    if b["adds_order_path"] and contract.execution_stage != "demo_code":
        blocks.append(Block("EXECUTION_BOUNDARY_EXPANSION", "order-capable path outside a demo_code Class C task"))
    legacy_files = [f for f in payload["files_changed"] if f.startswith(LEGACY_PREFIX)]
    if (b["touches_legacy"] or legacy_files) and not contract.legacy_mutation_authorized:
        blocks.append(Block("LEGACY_MUTATION_UNAUTHORIZED", f"legacy files changed: {legacy_files}"))
    if b["replaces_baseline"] or (contract.experiment is not None and payload.get("baseline_retained") is False):
        blocks.append(Block("BASELINE_OVERWRITTEN", "baseline must be compared, not overwritten"))
    if b["weakens_research_rule"]:
        blocks.append(Block("RESEARCH_RULE_WEAKENED", "implementation weakens a research rule"))
    outside = [f for f in payload["files_changed"] if not _in_scope(f, contract.scope_paths)]
    if outside:
        blocks.append(Block("SCOPE_VIOLATION", f"files outside contract scope: {sorted(outside)}"))
    return blocks


def evaluate_qa(required: Iterable[str], payload: Mapping[str, Any]) -> QAOutcome:
    flags = set(payload.get("evidence_flags", []))
    blockers = tuple(sorted(flags & BLOCKER_FLAGS))
    checks = payload["checks"]
    missing = tuple(sorted(c for c in required if c not in checks))
    failed = tuple(sorted(c for c in required if checks.get(c) is False))
    tests_ok = all(t["failed"] == 0 for t in payload["tests"]) and sum(t["passed"] for t in payload["tests"]) > 0
    notes = []
    if payload["verdict"] == "PASS" and (missing or not tests_ok or failed):
        notes.append("insufficient evidence reported as PASS; treated as FAIL")
    passed = payload["verdict"] == "PASS" and tests_ok and not missing and not failed and not blockers
    return QAOutcome(passed, missing, failed, blockers, tuple(notes))


def review_blockers(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(set(payload.get("evidence_flags", [])) & BLOCKER_FLAGS))


def approval_categories(classification: Classification) -> tuple[str, ...]:
    cats = set(classification.owner_sensitive)
    if classification.legacy_touch:
        cats.add("legacy_mutation")
    if classification.task_class == "C":
        cats.add("class_C")
    return tuple(sorted(cats))


def boundary_statement(contract: TaskContract) -> dict[str, Any]:
    """Recorded with every DONE: merge/completion never activates or promotes anything."""
    return {"activation_allowed": False, "merge_is_activation": False, "strategy_promoted": False,
            "execution_stage": contract.execution_stage, "demo_activation": "NOT_ALLOWED",
            "limited_live": "NOT_ALLOWED", "real_money": "NOT_ALLOWED"}


def _dedupe(blocks: list[Block]) -> list[Block]:
    seen, out = set(), []
    for block in blocks:
        if (block.code, block.reason) not in seen:
            seen.add((block.code, block.reason))
            out.append(block)
    return out
