"""Versioned TaskContract, Handoff and agent packet contracts (stdlib-only, strict)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from tools.owner_dev_policy.classification import DEFAULT_PRIORITY, PRIORITIES, Finding
from tools.owner_dev_policy.compute import EFFORTS, context_report, validate_budget
from tools.owner_dev_policy.schema import (DIGEST_RE, SHA_RE, boolean, canonical_json, choice, digest, integer,
                                           keys, obj, string, strings)

from .errors import ContractError
from .roles import AGENT_ROLES, PROFILES

TASK_CONTRACT_V1 = "atlas-devwf.task-contract.v1"
HANDOFF_V1 = "atlas-devwf.handoff.v1"
PACKET_V1 = "atlas-devwf.packet.v1"

TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,120}$")

TASK_CLASSES = ("A", "B", "C")
EXECUTION_STAGES = (
    "none", "replay", "backtest", "shadow", "demo_code", "demo_activation", "limited_live", "real_money",
)

# Owner-sensitive categories (binding default set).
OWNER_SENSITIVE = frozenset({
    "strategy_logic", "H4_last_impulse_semantics", "entry_stop_target_management", "risk_sizing",
    "portfolio_allocation", "cost_outcome_model", "holdout_evaluator_rules", "labels_ground_truth",
    "taint_causality", "execution_transport", "demo_activation", "production_live", "credentials",
    "destructive_schema",
})
# Additional non-owner-sensitive impact areas that still affect evidence/data semantics.
EVIDENCE_AREAS = frozenset({"evidence_data", "detector_capture", "macro_availability", "replay_identity"})
ENGINEERING_AREAS = frozenset({"engineering", "refactor", "docs", "tooling", "tests"})
IMPACT_AREAS = OWNER_SENSITIVE | EVIDENCE_AREAS | ENGINEERING_AREAS

# Evidence flags that are automatic blockers (promotion blockers are never waived by this runtime).
BLOCKER_FLAGS = frozenset({
    "holdout_exposed_outside_prereg", "tainted_evidence_as_operational_proof",
    "evaluator_edited_after_protected_results", "posthoc_outcome_or_cost_change",
    "adaptive_final_test_inspection", "lookahead_or_revised_unavailable_data",
    "rejected_candidate_evidence_missing", "baseline_overwritten", "leverage_only_improvement",
    "insufficient_evidence_as_pass",
})

PACKET_KINDS = {role: PROFILES[role].packet_kinds for role in AGENT_ROLES}  # one source: role profiles


# --- TaskContract v1 -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    prereg_digest: str
    evaluator_digest: str
    evaluator_frozen: bool
    baseline: str
    challenger: str
    search_set: tuple[str, ...]
    dataset_windows: tuple[str, ...]
    cost_model: str
    holdout_rules: str
    stopping_rules: str
    failed_result_persistence: bool
    confirmatory: bool = False
    protected_results_observed: bool = False
    evaluator_changed_after_protected_results: bool = False

    @classmethod
    def from_dict(cls, raw: Any) -> "ExperimentSpec":
        data = obj(raw, "experiment")
        required = {
            "experiment_id", "prereg_digest", "evaluator_digest", "evaluator_frozen", "baseline", "challenger",
            "search_set", "dataset_windows", "cost_model", "holdout_rules", "stopping_rules",
            "failed_result_persistence",
        }
        flags = {"confirmatory", "protected_results_observed", "evaluator_changed_after_protected_results"}
        keys(data, "experiment", required, flags)
        return cls(
            experiment_id=string(data["experiment_id"], "experiment.experiment_id"),
            prereg_digest=string(data["prereg_digest"], "experiment.prereg_digest", pattern=DIGEST_RE),
            evaluator_digest=string(data["evaluator_digest"], "experiment.evaluator_digest", pattern=DIGEST_RE),
            evaluator_frozen=boolean(data["evaluator_frozen"], "experiment.evaluator_frozen"),
            baseline=string(data["baseline"], "experiment.baseline"),
            challenger=string(data["challenger"], "experiment.challenger"),
            search_set=strings(data["search_set"], "experiment.search_set", nonempty=True),
            dataset_windows=strings(data["dataset_windows"], "experiment.dataset_windows", nonempty=True),
            cost_model=string(data["cost_model"], "experiment.cost_model"),
            holdout_rules=string(data["holdout_rules"], "experiment.holdout_rules"),
            stopping_rules=string(data["stopping_rules"], "experiment.stopping_rules"),
            failed_result_persistence=boolean(data["failed_result_persistence"], "experiment.failed_result_persistence"),
            **{k: boolean(data[k], f"experiment.{k}") for k in flags if k in data},
        )


@dataclass(frozen=True)
class HoldoutAccess:
    requested: bool
    via_preregistered_path: bool
    grant_id: str | None = None
    instrument_intervals: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Any) -> "HoldoutAccess":
        data = obj(raw, "holdout_access")
        keys(data, "holdout_access", {"requested", "via_preregistered_path"}, {"grant_id", "instrument_intervals"})
        grant = data.get("grant_id")
        return cls(
            requested=boolean(data["requested"], "holdout_access.requested"),
            via_preregistered_path=boolean(data["via_preregistered_path"], "holdout_access.via_preregistered_path"),
            grant_id=None if grant is None else string(grant, "holdout_access.grant_id"),
            instrument_intervals=strings(data.get("instrument_intervals", []), "holdout_access.instrument_intervals"),
        )


@dataclass(frozen=True)
class TaskContract:
    task_id: str
    title: str
    objective: str
    declared_class: str
    impact_areas: tuple[str, ...]
    scope_paths: tuple[str, ...]
    base_sha: str
    target_branch: str
    acceptance: tuple[str, ...]
    execution_stage: str = "none"
    activation_allowed: bool = False
    legacy_mutation_authorized: bool = False
    max_fix_cycles: int = 3
    branch: str | None = None
    experiment: ExperimentSpec | None = None
    holdout_access: HoldoutAccess | None = None
    notes: str = ""
    # Owner-policy fields. Priority orders the queue only; effort_override selects reasoning depth only;
    # neither changes classification, gates, checks or approvals.
    priority: str = DEFAULT_PRIORITY
    effort_override: str | None = None
    budget: dict[str, int] | None = None
    architecture_significant: bool = False
    schema_version: str = TASK_CONTRACT_V1

    @property
    def work_branch(self) -> str:
        return self.branch or f"devwf/{self.task_id}"

    @classmethod
    def from_dict(cls, raw: Any) -> "TaskContract":
        data = obj(raw, "contract")
        required = {"schema_version", "task_id", "title", "objective", "declared_class", "impact_areas",
                    "scope_paths", "base_sha", "target_branch", "acceptance"}
        optional = {"execution_stage", "activation_allowed", "legacy_mutation_authorized", "max_fix_cycles",
                    "branch", "experiment", "holdout_access", "notes", "priority", "effort_override", "budget",
                    "architecture_significant"}
        keys(data, "contract", required, optional)
        if data["schema_version"] != TASK_CONTRACT_V1:
            raise ContractError(f"contract: unsupported schema_version {data['schema_version']!r}")
        scope = strings(data["scope_paths"], "contract.scope_paths", nonempty=True)
        for path in scope:
            if path.startswith("/") or ".." in path.split("/"):
                raise ContractError("contract.scope_paths: must be repo-relative without '..'")
        branch = data.get("branch")
        return cls(
            task_id=string(data["task_id"], "contract.task_id", pattern=TASK_ID_RE),
            title=string(data["title"], "contract.title"),
            objective=string(data["objective"], "contract.objective"),
            declared_class=choice(data["declared_class"], "contract.declared_class", TASK_CLASSES),
            impact_areas=strings(data["impact_areas"], "contract.impact_areas", allowed=IMPACT_AREAS, nonempty=True),
            scope_paths=scope,
            base_sha=string(data["base_sha"], "contract.base_sha", pattern=SHA_RE),
            target_branch=string(data["target_branch"], "contract.target_branch", pattern=BRANCH_RE),
            acceptance=strings(data["acceptance"], "contract.acceptance", nonempty=True),
            execution_stage=choice(data.get("execution_stage", "none"), "contract.execution_stage", EXECUTION_STAGES),
            activation_allowed=boolean(data.get("activation_allowed", False), "contract.activation_allowed"),
            legacy_mutation_authorized=boolean(data.get("legacy_mutation_authorized", False),
                                             "contract.legacy_mutation_authorized"),
            max_fix_cycles=integer(data.get("max_fix_cycles", 3), "contract.max_fix_cycles", 1, 5),
            branch=None if branch is None else string(branch, "contract.branch", pattern=BRANCH_RE),
            experiment=None if data.get("experiment") is None else ExperimentSpec.from_dict(data["experiment"]),
            holdout_access=None if data.get("holdout_access") is None else HoldoutAccess.from_dict(data["holdout_access"]),
            notes=string(data.get("notes", ""), "contract.notes", empty=True),
            priority=choice(data.get("priority", DEFAULT_PRIORITY), "contract.priority", PRIORITIES),
            effort_override=None if data.get("effort_override") is None else choice(
                data["effort_override"], "contract.effort_override", EFFORTS),
            budget=None if data.get("budget") is None else validate_budget(data["budget"]),
            architecture_significant=boolean(data.get("architecture_significant", False),
                                             "contract.architecture_significant"),
            schema_version=TASK_CONTRACT_V1,
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("impact_areas", "scope_paths", "acceptance"):
            out[key] = list(out[key])
        if out["experiment"] is not None:
            for key in ("search_set", "dataset_windows"):
                out["experiment"][key] = list(out["experiment"][key])
        if out["holdout_access"] is not None:
            out["holdout_access"]["instrument_intervals"] = list(out["holdout_access"]["instrument_intervals"])
        return out

    @property
    def digest(self) -> str:
        return digest(TASK_CONTRACT_V1, self.to_dict())


# --- Handoff v1 ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Handoff:
    task_id: str
    role: str
    state: str
    step_key: str
    contract_digest: str
    task_class: str
    expected_kind: str
    instructions: str
    contract: dict[str, Any]
    required_checks: tuple[str, ...] = ()
    expected_head: str | None = None
    fix_cycle: int = 0
    prior_evidence: tuple[dict[str, Any], ...] = ()
    references: tuple[dict[str, Any], ...] = ()
    project_id: str = ""
    priority: str = DEFAULT_PRIORITY
    effort: str = "standard"
    context: dict[str, Any] = field(default_factory=context_report)
    schema_version: str = HANDOFF_V1

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["required_checks"] = list(self.required_checks)
        out["prior_evidence"] = [dict(e) for e in self.prior_evidence]
        out["references"] = [dict(r) for r in self.references]
        return out


# --- Agent packets v1 ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Packet:
    role: str
    kind: str
    task_id: str
    step_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = PACKET_V1

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "role": self.role, "kind": self.kind,
                "task_id": self.task_id, "step_key": self.step_key, "payload": self.payload}


_BOUNDARY_FIELDS = {"adds_order_path", "activates_demo", "activates_live", "touches_legacy",
                    "replaces_baseline", "weakens_research_rule"}


def _validate_plan(p: Mapping[str, Any]) -> None:
    keys(p, "plan", {"summary", "steps", "proposed_class", "impact_areas", "semantics_change", "rollback"},
          {"baseline_retained", "risks", "references", "experiment_required", "legacy_touch"})
    string(p["summary"], "plan.summary")
    strings(p["steps"], "plan.steps", nonempty=True)
    choice(p["proposed_class"], "plan.proposed_class", TASK_CLASSES)
    strings(p["impact_areas"], "plan.impact_areas", allowed=IMPACT_AREAS, nonempty=True)
    boolean(p["semantics_change"], "plan.semantics_change")
    string(p["rollback"], "plan.rollback")
    for key in ("baseline_retained", "experiment_required", "legacy_touch"):
        if key in p:
            boolean(p[key], f"plan.{key}")
    for key in ("risks", "references"):
        if key in p:
            strings(p[key], f"plan.{key}")


def _validate_implementation(p: Mapping[str, Any]) -> None:
    keys(p, "implementation", {"head_sha", "files_changed", "summary", "boundary"},
         {"baseline_retained", "notes", "finding_dispositions"})
    string(p["head_sha"], "implementation.head_sha", pattern=SHA_RE)
    files = strings(p["files_changed"], "implementation.files_changed")
    for path in files:
        if path.startswith("/") or ".." in path.split("/"):
            raise ContractError("implementation.files_changed: paths must be repo-relative")
    string(p["summary"], "implementation.summary")
    boundary = obj(p["boundary"], "implementation.boundary")
    keys(boundary, "implementation.boundary", _BOUNDARY_FIELDS)
    for key in _BOUNDARY_FIELDS:
        boolean(boundary[key], f"implementation.boundary.{key}")
    if "baseline_retained" in p:
        boolean(p["baseline_retained"], "implementation.baseline_retained")
    _findings(p.get("finding_dispositions", []), "implementation.finding_dispositions")


def _validate_qa(p: Mapping[str, Any], where: str) -> None:
    keys(p, where, {"head_sha", "verdict", "tests", "checks"}, {"evidence_flags", "notes"})
    string(p["head_sha"], f"{where}.head_sha", pattern=SHA_RE)
    choice(p["verdict"], f"{where}.verdict", ("PASS", "FAIL"))
    if not isinstance(p["tests"], list) or not p["tests"]:
        raise ContractError(f"{where}.tests: expected non-empty list (no PASS without executed tests)")
    for i, test in enumerate(p["tests"]):
        t = obj(test, f"{where}.tests[{i}]")
        keys(t, f"{where}.tests[{i}]", {"name", "command", "passed", "failed"}, {"skipped"})
        string(t["name"], f"{where}.tests[{i}].name")
        string(t["command"], f"{where}.tests[{i}].command")
        integer(t["passed"], f"{where}.tests[{i}].passed", 0, 10**7)
        integer(t["failed"], f"{where}.tests[{i}].failed", 0, 10**7)
        if "skipped" in t:
            integer(t["skipped"], f"{where}.tests[{i}].skipped", 0, 10**7)
    checks = obj(p["checks"], f"{where}.checks")
    for name, value in checks.items():
        string(name, f"{where}.checks key")
        boolean(value, f"{where}.checks.{name}")
    strings(p.get("evidence_flags", []), f"{where}.evidence_flags")


def _validate_review(p: Mapping[str, Any]) -> None:
    keys(p, "review", {"head_sha", "verdict", "findings", "promotion_claim"},
         {"evidence_flags", "notes", "maintainability_audit"})
    string(p["head_sha"], "review.head_sha", pattern=SHA_RE)
    choice(p["verdict"], "review.verdict", ("APPROVE", "REQUEST_CHANGES"))
    if not isinstance(p["findings"], list):
        raise ContractError("review.findings: expected list")
    for i, finding in enumerate(p["findings"]):
        f = obj(finding, f"review.findings[{i}]")
        keys(f, f"review.findings[{i}]", {"severity", "summary"}, {"path", "finding_id", "classification"})
        choice(f["severity"], f"review.findings[{i}].severity", ("info", "minor", "major", "critical"))
        string(f["summary"], f"review.findings[{i}].summary")
        if "classification" in f:
            Finding.from_dict({"finding_id": f.get("finding_id", f"F{i}"), "classification": f["classification"],
                               "summary": f["summary"]}, f"review.findings[{i}]")
    if boolean(p["promotion_claim"], "review.promotion_claim"):
        raise ContractError("review.promotion_claim: reviewer cannot promote a strategy")
    strings(p.get("evidence_flags", []), "review.evidence_flags")
    if "maintainability_audit" in p:
        audit = obj(p["maintainability_audit"], "review.maintainability_audit")
        keys(audit, "review.maintainability_audit", {"passed", "findings"})
        boolean(audit["passed"], "review.maintainability_audit.passed")
        _findings(audit["findings"], "review.maintainability_audit.findings")


def _findings(raw: Any, where: str) -> list[Finding]:
    if not isinstance(raw, list):
        raise ContractError(f"{where}: expected list")
    return [Finding.from_dict(f, f"{where}[{i}]") for i, f in enumerate(raw)]


def parse_packet(raw: Any, *, role: str, expected_kind: str, task_id: str, step_key: str) -> Packet:
    """Validate a structured agent packet against the handoff it answers."""
    data = obj(raw, "packet")
    keys(data, "packet", {"schema_version", "role", "kind", "task_id", "step_key", "payload"})
    if data["schema_version"] != PACKET_V1:
        raise ContractError(f"packet: unsupported schema_version {data['schema_version']!r}")
    if data["role"] != role:
        raise ContractError(f"packet: role {data['role']!r} does not match handoff role {role!r}")
    if data["kind"] != expected_kind or expected_kind not in PACKET_KINDS.get(role, ()):
        raise ContractError(f"packet: kind {data['kind']!r} not expected (want {expected_kind!r})")
    if data["task_id"] != task_id or data["step_key"] != step_key:
        raise ContractError("packet: task_id/step_key do not match handoff (stale or replayed packet)")
    payload = dict(obj(data["payload"], "packet.payload"))
    if expected_kind == "plan":
        _validate_plan(payload)
    elif expected_kind == "implementation":
        _validate_implementation(payload)
    elif expected_kind in ("qa_report", "verify_report"):
        _validate_qa(payload, expected_kind)
    elif expected_kind == "review":
        _validate_review(payload)
    return Packet(role=role, kind=expected_kind, task_id=task_id, step_key=step_key, payload=payload)
