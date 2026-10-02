"""Immutable evaluation/replay contracts for Atlas v2 P0-7."""
from __future__ import annotations

from dataclasses import dataclass
import json

from atlas2.core.canonical import canonical_json_text, domain_digest, validate_canonical_json_text
from atlas2.core.ids import make_id, validate_id
from atlas2.core.taint import Taint, combine_taint
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64
from atlas2.model.data import _instrument, _text

GATE_KINDS = frozenset({
    "DATA_QUALITY", "M15_COORDINATION", "H4_CONTEXT", "H1_CONTEXT",
    "CORRECTION_LOCATION", "SESSION_DAY", "NEWS_RISK", "SPREAD_COST",
})
GATE_OUTCOMES = frozenset({
    "PASS", "FAIL", "WAIT", "ABSTAIN", "NOT_APPLICABLE", "NOT_EVALUABLE", "ERROR",
})
ARM_DECISIONS = frozenset({"ACCEPT", "REJECT", "ABSTAIN", "NOT_ELIGIBLE", "ERROR"})
RELATION_KINDS = frozenset({"SAME_EVENT_DUPLICATE", "CONFIRMS", "PRIMARY_OF"})
GATE_ROLES = frozenset({"REQUIRED", "INFORMATIONAL"})
OUTCOME_STATUSES = frozenset({
    "RESOLVED", "AMBIGUOUS", "NOT_FILLED", "DATA_END", "INVALID_PLAN", "UNMEASURABLE",
})
PATH_RESOLUTIONS = frozenset({"M15_OHLC", "M1_OHLC", "TICK", "FIXTURE"})


def _canonical_sorted_ids(values, prefix: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("ID collection required")
    result = tuple(sorted(values))
    if result != tuple(sorted(set(result))):
        raise ValueError("IDs must be unique")
    for value in result:
        validate_id(value, prefix)
    return result


def canonical_input_refs(refs) -> tuple[dict, ...]:
    if isinstance(refs, (str, bytes)):
        raise ValueError("input refs must be a collection")
    values = []
    for ref in refs:
        if type(ref) is not dict or set(ref) != {"kind", "ref"}:
            raise ValueError("typed input ref requires kind + ref")
        if ref["kind"] not in {"SNAPSHOT", "LABEL_GROUP", "FACT", "RELATION"}:
            raise ValueError("invalid typed input ref kind")
        _text(ref["ref"])
        values.append({"kind": ref["kind"], "ref": ref["ref"]})
    values.sort(key=lambda item: (item["kind"], item["ref"]))
    if len({(item["kind"], item["ref"]) for item in values}) != len(values):
        raise ValueError("input refs must be unique")
    return tuple(values)


def canonical_gate_refs(refs) -> tuple[dict, ...]:
    if isinstance(refs, (str, bytes)):
        raise ValueError("gate refs must be a collection")
    values = []
    for ref in refs:
        if type(ref) is not dict or set(ref) != {"gate_id", "role"}:
            raise ValueError("gate ref requires gate_id + role")
        validate_id(ref["gate_id"], "gate")
        if ref["role"] not in GATE_ROLES:
            raise ValueError("invalid gate role")
        values.append({"gate_id": ref["gate_id"], "role": ref["role"]})
    if not values:
        raise ValueError("arm requires gate refs")
    if len({item["gate_id"] for item in values}) != len(values):
        raise ValueError("gate refs must be unique")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: str
    dataset_id: str
    instrument_id: str
    as_of_us: int
    view_class: str
    mode: str
    windows_json: str
    visible_fact_digest: str
    taint: int

    @classmethod
    def create(
        cls, *, dataset_id: str, instrument_id: str, as_of_us: int,
        view_class: str, mode: str, windows: object, visible_fact_ids, taint: int,
    ) -> "MarketSnapshot":
        fact_ids = tuple(sorted(visible_fact_ids))
        if fact_ids != tuple(sorted(set(fact_ids))):
            raise ValueError("visible fact IDs must be unique")
        for fact_id in fact_ids:
            validate_id(fact_id, ("fbar", "fqt", "fcs", "fcv"))
        windows_json = canonical_json_text(windows)
        visible_fact_digest = domain_digest("visible-facts-v1", list(fact_ids))
        payload = {
            "dataset_id": dataset_id,
            "instrument_id": instrument_id,
            "as_of_us": as_of_us,
            "view_class": view_class,
            "mode": mode,
            "windows": json.loads(windows_json),
            "visible_fact_digest": visible_fact_digest,
        }
        model = cls(
            make_id("snap", "market-snapshot-v1", payload),
            dataset_id, instrument_id, as_of_us, view_class, mode, windows_json,
            visible_fact_digest, int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.snapshot_id, "snap")
        validate_id(self.dataset_id, "ds")
        _instrument(self.instrument_id)
        validate_utc_micros(self.as_of_us)
        if self.view_class not in {"PIT", "NON_PIT"}:
            raise ValueError("invalid snapshot view class")
        if self.mode not in {"REPLAY", "FORWARD"}:
            raise ValueError("invalid snapshot mode")
        validate_canonical_json_text(self.windows_json)
        windows = json.loads(self.windows_json)
        if type(windows) is not list:
            raise ValueError("snapshot windows must be a list")
        encoded_windows = [canonical_json_text(window) for window in windows]
        if encoded_windows != sorted(encoded_windows) or len(encoded_windows) != len(set(encoded_windows)):
            raise ValueError("snapshot windows must be sorted and unique")
        if len(self.visible_fact_digest) != 64:
            raise ValueError("visible fact digest must be SHA-256 hex")
        int(self.visible_fact_digest, 16)
        combine_taint(self.taint)
        expected = make_id("snap", "market-snapshot-v1", {
            "dataset_id": self.dataset_id,
            "instrument_id": self.instrument_id,
            "as_of_us": self.as_of_us,
            "view_class": self.view_class,
            "mode": self.mode,
            "windows": json.loads(self.windows_json),
            "visible_fact_digest": self.visible_fact_digest,
        })
        if self.snapshot_id != expected:
            raise ValueError("snapshot identity mismatch")


@dataclass(frozen=True, slots=True)
class CaptureUnit:
    capture_unit_id: str
    dataset_id: str
    instrument_id: str
    decision_time_us: int
    snapshot_id: str
    candidate_ids_json: str
    semantic_capture_digest: str

    @classmethod
    def create(
        cls, *, dataset_id: str, instrument_id: str, decision_time_us: int,
        snapshot_id: str, candidate_ids, semantic_capture_digest: str,
    ) -> "CaptureUnit":
        ids = _canonical_sorted_ids(candidate_ids, "cand")
        payload = {
            "dataset_id": dataset_id,
            "instrument_id": instrument_id,
            "decision_time_us": decision_time_us,
            "snapshot_id": snapshot_id,
            "semantic_capture_digest": semantic_capture_digest,
        }
        model = cls(
            make_id("capu", "capture-unit-v1", payload),
            dataset_id, instrument_id, decision_time_us, snapshot_id,
            canonical_json_text(list(ids)), semantic_capture_digest,
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.capture_unit_id, "capu")
        validate_id(self.dataset_id, "ds")
        _instrument(self.instrument_id)
        validate_utc_micros(self.decision_time_us)
        validate_id(self.snapshot_id, "snap")
        validate_canonical_json_text(self.candidate_ids_json)
        ids = tuple(json.loads(self.candidate_ids_json))
        if ids != tuple(sorted(set(ids))):
            raise ValueError("candidate IDs must be sorted and unique")
        for candidate_id in ids:
            validate_id(candidate_id, "cand")
        if len(self.semantic_capture_digest) != 64:
            raise ValueError("semantic capture digest must be SHA-256 hex")
        int(self.semantic_capture_digest, 16)
        expected = make_id("capu", "capture-unit-v1", {
            "dataset_id": self.dataset_id,
            "instrument_id": self.instrument_id,
            "decision_time_us": self.decision_time_us,
            "snapshot_id": self.snapshot_id,
            "semantic_capture_digest": self.semantic_capture_digest,
        })
        if self.capture_unit_id != expected:
            raise ValueError("capture unit identity mismatch")


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    ctx_id: str
    capture_unit_id: str
    label_pin_id: str | None
    macro_view_class: str
    mode: str
    taint: int

    @classmethod
    def create(
        cls, *, capture_unit_id: str, label_pin_id: str | None,
        macro_view_class: str, mode: str, taint: int,
    ) -> "EvaluationContext":
        payload = {
            "capture_unit_id": capture_unit_id,
            "label_pin_id": label_pin_id,
            "macro_view_class": macro_view_class,
            "mode": mode,
        }
        model = cls(
            make_id("ctx", "evaluation-context-v1", payload),
            capture_unit_id, label_pin_id, macro_view_class, mode, int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.ctx_id, "ctx")
        validate_id(self.capture_unit_id, "capu")
        if self.label_pin_id is not None:
            validate_id(self.label_pin_id, "lpin")
        if self.macro_view_class not in {"PIT", "NON_PIT"}:
            raise ValueError("invalid macro view class")
        if self.mode not in {"REPLAY", "FORWARD"}:
            raise ValueError("invalid evaluation mode")
        combine_taint(self.taint)
        expected = make_id("ctx", "evaluation-context-v1", {
            "capture_unit_id": self.capture_unit_id,
            "label_pin_id": self.label_pin_id,
            "macro_view_class": self.macro_view_class,
            "mode": self.mode,
        })
        if self.ctx_id != expected:
            raise ValueError("evaluation context identity mismatch")


@dataclass(frozen=True, slots=True)
class CandidateRelation:
    relation_id: str
    ctx_id: str
    relation_kind: str
    evaluator_version_id: str
    primary_candidate_id: str
    other_candidate_id: str
    taint: int

    @classmethod
    def create(
        cls, *, ctx_id: str, relation_kind: str, evaluator_version_id: str,
        primary_candidate_id: str, other_candidate_id: str, taint: int,
    ) -> "CandidateRelation":
        payload = {
            "ctx_id": ctx_id,
            "relation_kind": relation_kind,
            "evaluator_version_id": evaluator_version_id,
            "primary_candidate_id": primary_candidate_id,
            "other_candidate_id": other_candidate_id,
        }
        model = cls(
            make_id("rel", "candidate-relation-v1", payload),
            ctx_id, relation_kind, evaluator_version_id,
            primary_candidate_id, other_candidate_id, int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.relation_id, "rel")
        validate_id(self.ctx_id, "ctx")
        if self.relation_kind not in RELATION_KINDS:
            raise ValueError("invalid relation kind")
        _text(self.evaluator_version_id)
        validate_id(self.primary_candidate_id, "cand")
        validate_id(self.other_candidate_id, "cand")
        if self.primary_candidate_id == self.other_candidate_id:
            raise ValueError("relation endpoints must differ")
        combine_taint(self.taint)
        expected = make_id("rel", "candidate-relation-v1", {
            "ctx_id": self.ctx_id,
            "relation_kind": self.relation_kind,
            "evaluator_version_id": self.evaluator_version_id,
            "primary_candidate_id": self.primary_candidate_id,
            "other_candidate_id": self.other_candidate_id,
        })
        if self.relation_id != expected:
            raise ValueError("relation identity mismatch")


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    ctx_id: str
    candidate_id: str
    gate_kind: str
    evaluator_version_id: str
    input_refs_json: str
    outcome: str
    reason_code: str | None
    error_code: str | None
    measurements_json: str
    taint: int

    @classmethod
    def create(
        cls, *, ctx_id: str, candidate_id: str, gate_kind: str,
        evaluator_version_id: str, input_refs, outcome: str,
        reason_code: str | None, error_code: str | None,
        measurements: object, taint: int,
    ) -> "GateResult":
        refs = canonical_input_refs(input_refs)
        payload = {
            "ctx_id": ctx_id,
            "candidate_id": candidate_id,
            "gate_kind": gate_kind,
            "evaluator_version_id": evaluator_version_id,
            "input_refs": list(refs),
        }
        model = cls(
            make_id("gate", "gate-result-v1", payload),
            ctx_id, candidate_id, gate_kind, evaluator_version_id,
            canonical_json_text(list(refs)), outcome, reason_code, error_code,
            canonical_json_text(measurements), int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.gate_id, "gate")
        validate_id(self.ctx_id, "ctx")
        validate_id(self.candidate_id, "cand")
        if self.gate_kind not in GATE_KINDS:
            raise ValueError("invalid gate kind")
        _text(self.evaluator_version_id)
        validate_canonical_json_text(self.input_refs_json)
        refs = canonical_input_refs(json.loads(self.input_refs_json))
        if canonical_json_text(list(refs)) != self.input_refs_json:
            raise ValueError("input refs are not canonical")
        if self.outcome not in GATE_OUTCOMES:
            raise ValueError("invalid gate outcome")
        if self.reason_code is not None:
            _text(self.reason_code)
        if self.error_code is not None:
            _text(self.error_code)
        if self.outcome == "ERROR" and self.error_code is None:
            raise ValueError("ERROR gate requires error_code")
        validate_canonical_json_text(self.measurements_json)
        measurements = json.loads(self.measurements_json)
        if type(measurements) is not list:
            raise ValueError("gate measurements must be a list")
        for measurement in measurements:
            if type(measurement) is not dict or set(measurement) != {"name", "value", "unit"}:
                raise ValueError("measurement requires name, value, unit")
            _text(measurement["name"]); _text(measurement["unit"]); validate_int64(measurement["value"])
        if self.gate_kind == "CORRECTION_LOCATION" and self.outcome not in {"NOT_APPLICABLE", "ERROR"}:
            raise ValueError("CORRECTION_LOCATION is measurement-only")
        combine_taint(self.taint)
        expected = make_id("gate", "gate-result-v1", {
            "ctx_id": self.ctx_id,
            "candidate_id": self.candidate_id,
            "gate_kind": self.gate_kind,
            "evaluator_version_id": self.evaluator_version_id,
            "input_refs": list(refs),
        })
        if self.gate_id != expected:
            raise ValueError("gate identity mismatch")


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    strategy_version_id: str
    strategy_key: str
    version: str
    gate_roles_json: str
    plan_json: str

    @classmethod
    def create(
        cls, *, strategy_key: str, version: str, gate_roles, plan: object,
    ) -> "StrategyVersion":
        roles = tuple(gate_roles)
        for item in roles:
            if type(item) is not dict or set(item) != {"gate_kind", "role"}:
                raise ValueError("strategy gate role requires gate_kind + role")
            if item["gate_kind"] not in GATE_KINDS:
                raise ValueError("invalid strategy gate kind")
            if item["role"] not in GATE_ROLES:
                raise ValueError("invalid strategy gate role")
        if len({item["gate_kind"] for item in roles}) != len(roles):
            raise ValueError("strategy gate roles must be unique by kind")
        payload = {
            "strategy_key": strategy_key,
            "version": version,
            "gate_roles": list(roles),
            "plan": plan,
        }
        model = cls(
            make_id("strat", "strategy-version-v1", payload),
            strategy_key, version, canonical_json_text(list(roles)),
            canonical_json_text(plan),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.strategy_version_id, "strat")
        _text(self.strategy_key)
        _text(self.version)
        validate_canonical_json_text(self.gate_roles_json)
        validate_canonical_json_text(self.plan_json)
        roles = json.loads(self.gate_roles_json)
        for item in roles:
            if type(item) is not dict or set(item) != {"gate_kind", "role"}:
                raise ValueError("invalid strategy gate role")
            if item["gate_kind"] not in GATE_KINDS or item["role"] not in GATE_ROLES:
                raise ValueError("invalid strategy gate role")
        if len({item["gate_kind"] for item in roles}) != len(roles):
            raise ValueError("strategy gate roles must be unique by kind")
        expected = make_id("strat", "strategy-version-v1", {
            "strategy_key": self.strategy_key, "version": self.version,
            "gate_roles": roles, "plan": json.loads(self.plan_json),
        })
        if self.strategy_version_id != expected:
            raise ValueError("strategy version identity mismatch")


@dataclass(frozen=True, slots=True)
class ArmResult:
    arm_id: str
    candidate_id: str
    strategy_version_id: str
    ctx_id: str
    gate_refs_json: str
    decision: str
    reason_codes_json: str
    plan_json: str
    taint: int

    @classmethod
    def create(
        cls, *, candidate_id: str, strategy_version_id: str, ctx_id: str,
        gate_refs, decision: str, reason_codes, plan: object, taint: int,
    ) -> "ArmResult":
        refs = canonical_gate_refs(gate_refs)
        reasons = tuple(reason_codes)
        payload = {
            "candidate_id": candidate_id,
            "strategy_version_id": strategy_version_id,
            "ctx_id": ctx_id,
            "gate_refs": list(refs),
        }
        model = cls(
            make_id("arm", "arm-result-v1", payload),
            candidate_id, strategy_version_id, ctx_id,
            canonical_json_text(list(refs)), decision,
            canonical_json_text(list(reasons)), canonical_json_text(plan),
            int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.arm_id, "arm")
        validate_id(self.candidate_id, "cand")
        validate_id(self.strategy_version_id, "strat")
        validate_id(self.ctx_id, "ctx")
        validate_canonical_json_text(self.gate_refs_json)
        refs = canonical_gate_refs(json.loads(self.gate_refs_json))
        if canonical_json_text(list(refs)) != self.gate_refs_json:
            raise ValueError("gate refs are not canonical")
        if self.decision not in ARM_DECISIONS:
            raise ValueError("invalid arm decision")
        validate_canonical_json_text(self.reason_codes_json)
        reasons = json.loads(self.reason_codes_json)
        if self.decision != "ACCEPT" and not reasons:
            raise ValueError("non-ACCEPT arm requires reason code")
        for reason in reasons:
            _text(reason)
        validate_canonical_json_text(self.plan_json)
        combine_taint(self.taint)
        expected = make_id("arm", "arm-result-v1", {
            "candidate_id": self.candidate_id,
            "strategy_version_id": self.strategy_version_id,
            "ctx_id": self.ctx_id,
            "gate_refs": list(refs),
        })
        if self.arm_id != expected:
            raise ValueError("arm identity mismatch")


@dataclass(frozen=True, slots=True)
class OutcomeBatch:
    batch_id: str
    dataset_id: str
    fixture_name: str

    @classmethod
    def create(cls, *, dataset_id: str, fixture_name: str) -> "OutcomeBatch":
        model = cls(
            make_id("outb", "outcome-batch-v1", {
                "dataset_id": dataset_id, "fixture_name": fixture_name,
            }),
            dataset_id, fixture_name,
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.batch_id, "outb")
        validate_id(self.dataset_id, "ds")
        _text(self.fixture_name)
        expected = make_id("outb", "outcome-batch-v1", {
            "dataset_id": self.dataset_id, "fixture_name": self.fixture_name,
        })
        if self.batch_id != expected:
            raise ValueError("outcome batch identity mismatch")


@dataclass(frozen=True, slots=True)
class OutcomeAttachment:
    outcome_id: str
    batch_id: str
    subject_kind: str
    subject_ref: str
    reference_plan_id: str | None
    resolver_version_id: str
    cost_model_version_id: str
    dataset_id: str
    status: str
    entry_time_us: int | None
    r_low_micro: int | None
    r_high_micro: int | None
    exit_reason: str | None
    be_triggered: bool | None
    mae_micro: int | None
    mfe_micro: int | None
    path_resolution: str | None
    taint: int

    @classmethod
    def create(
        cls, *, batch_id: str, subject_kind: str, subject_ref: str,
        reference_plan_id: str | None, resolver_version_id: str,
        cost_model_version_id: str, dataset_id: str, status: str,
        entry_time_us: int | None, r_low_micro: int | None,
        r_high_micro: int | None, exit_reason: str | None,
        be_triggered: bool | None, mae_micro: int | None, mfe_micro: int | None,
        path_resolution: str | None, taint: int,
    ) -> "OutcomeAttachment":
        payload = {
            "subject_kind": subject_kind,
            "subject_ref": subject_ref,
            "reference_plan_id": reference_plan_id,
            "resolver_version_id": resolver_version_id,
            "cost_model_version_id": cost_model_version_id,
            "dataset_id": dataset_id,
        }
        model = cls(
            make_id("out", "outcome-attachment-v1", payload),
            batch_id, subject_kind, subject_ref, reference_plan_id,
            resolver_version_id, cost_model_version_id, dataset_id, status,
            entry_time_us, r_low_micro, r_high_micro, exit_reason,
            be_triggered, mae_micro, mfe_micro, path_resolution, int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.outcome_id, "out")
        validate_id(self.batch_id, "outb")
        if self.subject_kind not in {"ARM", "CANDIDATE_REFERENCE"}:
            raise ValueError("invalid outcome subject kind")
        validate_id(self.subject_ref, "arm" if self.subject_kind == "ARM" else "cand")
        if self.subject_kind == "CANDIDATE_REFERENCE":
            if self.reference_plan_id is None:
                raise ValueError("candidate counterfactual needs reference plan")
        elif self.reference_plan_id is not None:
            raise ValueError("arm outcome cannot have reference plan")
        if self.reference_plan_id is not None:
            _text(self.reference_plan_id)
        _text(self.resolver_version_id)
        _text(self.cost_model_version_id)
        validate_id(self.dataset_id, "ds")
        if self.status not in OUTCOME_STATUSES:
            raise ValueError("invalid outcome status")
        if self.entry_time_us is not None:
            validate_utc_micros(self.entry_time_us)
        for value in (self.r_low_micro, self.r_high_micro, self.mae_micro, self.mfe_micro):
            if value is not None:
                validate_int64(value)
        if self.r_low_micro is not None and self.r_high_micro is not None:
            if self.r_low_micro > self.r_high_micro:
                raise ValueError("invalid R interval")
        if self.exit_reason is not None:
            _text(self.exit_reason)
        if self.be_triggered is not None and type(self.be_triggered) is not bool:
            raise TypeError("be_triggered must be bool or None")
        if self.path_resolution is not None and self.path_resolution not in PATH_RESOLUTIONS:
            raise ValueError("invalid path resolution")
        combine_taint(self.taint)
        expected = make_id("out", "outcome-attachment-v1", {
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "reference_plan_id": self.reference_plan_id,
            "resolver_version_id": self.resolver_version_id,
            "cost_model_version_id": self.cost_model_version_id,
            "dataset_id": self.dataset_id,
        })
        if self.outcome_id != expected:
            raise ValueError("outcome identity mismatch")
