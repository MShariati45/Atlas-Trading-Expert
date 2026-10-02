"""Evaluation ledger, C0 control, and P0 fixture outcome persistence."""
from __future__ import annotations

from dataclasses import asdict
import json

from atlas2.core.canonical import domain_digest
from atlas2.core.taint import Taint, combine_taint
from atlas2.evaluate.c0_control import decide
from atlas2.model.evaluation import (
    ArmResult, GateResult, OutcomeAttachment, OutcomeBatch, StrategyVersion,
)
from atlas2.store.repository import ConflictKind, Store, StoreConflict


def insert_exact(conn, table: str, key_column: str, model) -> None:
    values = asdict(model)
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {key_column}=?", (values[key_column],)
    ).fetchone()
    if row is None:
        conn.execute(
            f"INSERT INTO {table}({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )
    elif dict(row) != values:
        raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)


def identity_conflict() -> StoreConflict:
    return StoreConflict(ConflictKind.IDENTITY_CONFLICT)


def c0_strategy() -> StrategyVersion:
    return StrategyVersion.create(
        strategy_key="C0_MINIMAL_CONTROL",
        version="v1",
        gate_roles=[{"gate_kind": "DATA_QUALITY", "role": "REQUIRED"}],
        plan={"plan_id": "C0_REFERENCE_ONLY", "execution": "NONE"},
    )


def register_c0_strategy(store: Store) -> StrategyVersion:
    model = c0_strategy()
    with store.transaction():
        insert_exact(store.conn, "strategy_versions", "strategy_version_id", model)
    return model


def _candidate_quality_flags(
    store: Store, dataset_id: str, candidate_row, decision_time_us: int, mode: str
) -> int | None:
    refs = json.loads(candidate_row["evidence_refs_json"])
    flags = 0
    for fact_id in refs:
        rows = store.conn.execute(
            """SELECT l.quality_flags,l.available_at_us,l.availability_basis,o.acquired_at_us
               FROM data_dataset_membership m
               JOIN data_fact_links l
                 ON l.fact_id=m.fact_id AND l.obs_id=m.obs_id AND l.locator=m.locator
               JOIN source_observations o ON o.obs_id=m.obs_id
               WHERE m.dataset_id=? AND m.fact_id=?""",
            (dataset_id, fact_id),
        ).fetchall()
        eligible = []
        for row in rows:
            if row["availability_basis"] == "UNKNOWN" or row["available_at_us"] is None:
                continue
            knowledge = row["available_at_us"]
            if mode == "FORWARD":
                knowledge = max(knowledge, row["acquired_at_us"])
            if knowledge <= decision_time_us:
                eligible.append(row)
        if not eligible:
            return None
        for row in eligible:
            flags |= row["quality_flags"]
    return flags


def _insert_evaluation_member(store: Store, ctx_id: str, kind: str, member_id: str, semantic: object) -> str:
    digest = domain_digest("evaluation-member-v1", semantic)
    store.conn.execute(
        "INSERT INTO evaluation_unit_members VALUES (?,?,?,?)",
        (ctx_id, kind, member_id, digest),
    )
    return digest


def _load_context_capture(store: Store, ctx_id: str):
    context = store.conn.execute(
        "SELECT * FROM evaluation_contexts WHERE ctx_id=?", (ctx_id,)
    ).fetchone()
    if context is None:
        raise ValueError("unknown evaluation context")
    capture = store.conn.execute(
        "SELECT * FROM capture_units WHERE capture_unit_id=?", (context["capture_unit_id"],)
    ).fetchone()
    if capture is None:
        raise ValueError("unknown capture unit")
    return context, capture


def _existing_strategy_arms(
    store: Store, *, ctx_id: str, strategy: StrategyVersion
) -> list[ArmResult]:
    rows = store.conn.execute(
        """SELECT a.* FROM arm_results a
           JOIN candidates c ON c.candidate_id=a.candidate_id
           WHERE a.ctx_id=? AND a.strategy_version_id=?
           ORDER BY c.occurrence_key,a.candidate_id""",
        (ctx_id, strategy.strategy_version_id),
    ).fetchall()
    return [ArmResult(**dict(row)) for row in rows]


def _evaluate_c0_unsealed(
    store: Store,
    *,
    context,
    capture,
    fault_after_first_gate: bool = False,
) -> list[ArmResult]:
    strategy = c0_strategy()
    insert_exact(store.conn, "strategy_versions", "strategy_version_id", strategy)
    candidates = store.conn.execute(
        """SELECT c.*
           FROM capture_unit_members m
           JOIN candidates c ON c.candidate_id=m.member_id
           WHERE m.capture_unit_id=? AND m.member_kind='CANDIDATE'
           ORDER BY c.occurrence_key,c.candidate_id""",
        (capture["capture_unit_id"],),
    ).fetchall()
    result = []
    for index, candidate in enumerate(candidates):
        flags = _candidate_quality_flags(
            store, capture["dataset_id"], candidate, capture["decision_time_us"], context["mode"]
        )
        if flags is None:
            outcome = "NOT_EVALUABLE"
            reason_code = "EVIDENCE_NOT_VISIBLE"
            flag_measurement = 0
        else:
            outcome = "PASS" if flags == 0 else "FAIL"
            reason_code = None if flags == 0 else "DATA_QUALITY_FLAGGED"
            flag_measurement = flags
        refs = [{"kind": "SNAPSHOT", "ref": capture["snapshot_id"]}]
        refs.extend(
            {"kind": "FACT", "ref": fact_id}
            for fact_id in json.loads(candidate["evidence_refs_json"])
        )
        gate = GateResult.create(
            ctx_id=context["ctx_id"],
            candidate_id=candidate["candidate_id"],
            gate_kind="DATA_QUALITY",
            evaluator_version_id="c0-data-quality-v1",
            input_refs=refs,
            outcome=outcome,
            reason_code=reason_code,
            error_code=None,
            measurements=[
                {"name": "quality_flag_union", "value": flag_measurement, "unit": "bitset"}
            ],
            taint=int(combine_taint(context["taint"], candidate["taint"])),
        )
        insert_exact(store.conn, "gate_results", "gate_id", gate)
        gate_semantic = {
            "occurrence_key": candidate["occurrence_key"],
            "gate_kind": gate.gate_kind,
            "evaluator_version_id": gate.evaluator_version_id,
            "snapshot_visible_fact_digest": store.conn.execute(
                "SELECT visible_fact_digest FROM market_snapshots WHERE snapshot_id=?",
                (capture["snapshot_id"],),
            ).fetchone()[0],
            "fact_refs": sorted(json.loads(candidate["evidence_refs_json"])),
            "outcome": gate.outcome,
            "reason_code": gate.reason_code,
            "error_code": gate.error_code,
            "measurements": json.loads(gate.measurements_json),
            "taint": gate.taint,
        }
        gate_digest = _insert_evaluation_member(
            store, context["ctx_id"], "GATE", gate.gate_id, gate_semantic
        )
        if fault_after_first_gate and index == 0:
            raise RuntimeError("P0_7_INJECTED_GATE_FAULT")

        decision, reasons = decide(outcome)
        arm = ArmResult.create(
            candidate_id=candidate["candidate_id"],
            strategy_version_id=strategy.strategy_version_id,
            ctx_id=context["ctx_id"],
            gate_refs=[{"gate_id": gate.gate_id, "role": "REQUIRED"}],
            decision=decision,
            reason_codes=reasons,
            plan=json.loads(strategy.plan_json),
            taint=gate.taint,
        )
        insert_exact(store.conn, "arm_results", "arm_id", arm)
        arm_semantic = {
            "occurrence_key": candidate["occurrence_key"],
            "strategy_key": strategy.strategy_key,
            "strategy_version": strategy.version,
            "gate_content_digests": [gate_digest],
            "decision": arm.decision,
            "reason_codes": json.loads(arm.reason_codes_json),
            "plan": json.loads(arm.plan_json),
            "taint": arm.taint,
        }
        _insert_evaluation_member(
            store, context["ctx_id"], "ARM", arm.arm_id, arm_semantic
        )
        result.append(arm)
    return result


def evaluate_c0(
    store: Store,
    *,
    ctx_id: str,
    fault_after_first_gate: bool = False,
) -> list[ArmResult]:
    context, capture = _load_context_capture(store, ctx_id)
    strategy = c0_strategy()
    if store.conn.execute(
        "SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=?",
        (ctx_id,),
    ).fetchone():
        return _existing_strategy_arms(store, ctx_id=ctx_id, strategy=strategy)

    with store.transaction():
        result = _evaluate_c0_unsealed(
            store,
            context=context,
            capture=capture,
            fault_after_first_gate=fault_after_first_gate,
        )
        store.seal_current_transaction("evaluation_contexts", ctx_id)
        return result


def persist_fixture_outcome_batch(
    store: Store,
    *,
    dataset_id: str,
    fixture_name: str,
    attachments: list[dict],
) -> OutcomeBatch:
    batch = OutcomeBatch.create(dataset_id=dataset_id, fixture_name=fixture_name)
    models = []
    semantics = []
    for item in attachments:
        payload = dict(item)
        payload["batch_id"] = batch.batch_id
        payload["dataset_id"] = dataset_id
        if payload.get("path_resolution") != "FIXTURE":
            raise ValueError("P0 outcome rows must be hand-built FIXTURE outcomes")

        subject_kind = payload.get("subject_kind")
        subject_ref = payload.get("subject_ref")
        if subject_kind == "ARM":
            subject = store.conn.execute(
                """SELECT c.occurrence_key,s.strategy_key,s.version,
                          i.dataset_id,u.decision_time_us,a.taint AS subject_taint
                   FROM arm_results a
                   JOIN candidates c ON c.candidate_id=a.candidate_id
                   JOIN raw_detection_receipts r ON r.receipt_id=c.receipt_id
                   JOIN detector_invocations i ON i.invocation_id=r.invocation_id
                   JOIN strategy_versions s ON s.strategy_version_id=a.strategy_version_id
                   JOIN evaluation_contexts x ON x.ctx_id=a.ctx_id
                   JOIN capture_units u ON u.capture_unit_id=x.capture_unit_id
                   WHERE a.arm_id=?""",
                (subject_ref,),
            ).fetchone()
            if subject is None:
                raise ValueError("unknown ARM outcome subject")
            if subject["dataset_id"] != dataset_id:
                raise ValueError("outcome subject dataset mismatch")
            decision_time_us = subject["decision_time_us"]
            subject_semantic = {
                "kind": "ARM",
                "occurrence_key": subject["occurrence_key"],
                "strategy_key": subject["strategy_key"],
                "strategy_version": subject["version"],
            }
        elif subject_kind == "CANDIDATE_REFERENCE":
            subject = store.conn.execute(
                """SELECT c.occurrence_key,c.available_at_us,i.dataset_id,
                          c.taint AS subject_taint
                   FROM candidates c
                   JOIN raw_detection_receipts r ON r.receipt_id=c.receipt_id
                   JOIN detector_invocations i ON i.invocation_id=r.invocation_id
                   WHERE c.candidate_id=?""",
                (subject_ref,),
            ).fetchone()
            if subject is None:
                raise ValueError("unknown candidate outcome subject")
            if subject["dataset_id"] != dataset_id:
                raise ValueError("outcome subject dataset mismatch")
            decision_time_us = subject["available_at_us"]
            subject_semantic = {
                "kind": "CANDIDATE_REFERENCE",
                "occurrence_key": subject["occurrence_key"],
                "reference_plan_id": payload.get("reference_plan_id"),
            }
        else:
            raise ValueError("invalid outcome subject kind")

        payload["taint"] = int(combine_taint(
            payload.get("taint", 0), subject["subject_taint"], Taint.SYNTHETIC_DATA
        ))
        model = OutcomeAttachment.create(**payload)
        if model.entry_time_us is not None and model.entry_time_us < decision_time_us:
            raise ValueError("outcome entry precedes decision time")
        models.append(model)
        semantics.append({
            "subject": subject_semantic,
            "resolver_version_id": model.resolver_version_id,
            "cost_model_version_id": model.cost_model_version_id,
            "status": model.status,
            "entry_time_us": model.entry_time_us,
            "r_low_micro": model.r_low_micro,
            "r_high_micro": model.r_high_micro,
            "exit_reason": model.exit_reason,
            "be_triggered": model.be_triggered,
            "mae_micro": model.mae_micro,
            "mfe_micro": model.mfe_micro,
            "path_resolution": model.path_resolution,
            "taint": model.taint,
        })

    with store.transaction():
        insert_exact(store.conn, "outcome_batches", "batch_id", batch)
        if store.conn.execute(
            "SELECT 1 FROM sys_seals WHERE aggregate_kind='outcome_batches' AND aggregate_id=?",
            (batch.batch_id,),
        ).fetchone():
            expected_digests = sorted(
                domain_digest("outcome-member-v1", semantic) for semantic in semantics
            )
            expected_ids = sorted(model.outcome_id for model in models)
            stored_rows = store.conn.execute(
                "SELECT outcome_id,content_digest FROM outcome_batch_members "
                "WHERE batch_id=? ORDER BY outcome_id,content_digest",
                (batch.batch_id,),
            ).fetchall()
            stored_ids = sorted(row["outcome_id"] for row in stored_rows)
            stored_digests = sorted(row["content_digest"] for row in stored_rows)
            if stored_ids != expected_ids or stored_digests != expected_digests:
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
            return batch
        for model, semantic in zip(models, semantics):
            insert_exact(store.conn, "outcome_attachments", "outcome_id", model)
            store.conn.execute(
                "INSERT INTO outcome_batch_members VALUES (?,?,?)",
                (
                    batch.batch_id,
                    model.outcome_id,
                    domain_digest("outcome-member-v1", semantic),
                ),
            )
        store.seal_current_transaction("outcome_batches", batch.batch_id)
    return batch
