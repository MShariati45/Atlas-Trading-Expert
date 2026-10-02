"""P1 Track A evaluation integration over fresh, unsealed contexts."""
from __future__ import annotations

from dataclasses import dataclass
import json

from atlas2.core.taint import combine_taint
from atlas2.evaluate.gates.correction_location import evaluate_correction_location
from atlas2.evaluate.ledger import (
    _evaluate_c0_unsealed,
    _existing_strategy_arms,
    _insert_evaluation_member,
    _load_context_capture,
    c0_strategy,
    insert_exact,
)
from atlas2.model.evaluation import ArmResult, GateResult, StrategyVersion
from atlas2.strategy.owner_entry import owner_track_a_strategy


@dataclass(frozen=True, slots=True)
class P1EvaluationResult:
    c0_arms: tuple[ArmResult, ...]
    owner_arms: tuple[ArmResult, ...]


_PENDING_GATES = {
    "M15_COORDINATION": (
        "p1-m15-owner-policy-v1",
        "NOT_EVALUABLE",
        "OWNER_M15_OPERATIONAL_SEMANTICS_PENDING",
    ),
    "H4_CONTEXT": (
        "p1-h4-context-v1",
        "NOT_EVALUABLE",
        "H4_CONTEXT_EVALUATOR_PENDING",
    ),
    "H1_CONTEXT": (
        "p1-h1-context-v1",
        "NOT_EVALUABLE",
        "H1_CONTEXT_EVALUATOR_PENDING",
    ),
    "SESSION_DAY": (
        "p1-session-day-v1",
        "NOT_EVALUABLE",
        "SESSION_DAY_EVALUATOR_PENDING",
    ),
    "NEWS_RISK": (
        "p1-news-risk-v1",
        "NOT_EVALUABLE",
        "NEWS_RISK_EVALUATOR_PENDING",
    ),
    "SPREAD_COST": (
        "p1-spread-cost-v1",
        "NOT_EVALUABLE",
        "SPREAD_COST_EVALUATOR_PENDING",
    ),
}


def _decision_from_required(gates: dict[str, GateResult], strategy: StrategyVersion):
    roles = json.loads(strategy.gate_roles_json)
    required = [
        gates[item["gate_kind"]]
        for item in roles
        if item["role"] == "REQUIRED"
    ]
    errors = sorted(gate.gate_kind for gate in required if gate.outcome == "ERROR")
    if errors:
        return "ERROR", tuple(f"{kind}_ERROR" for kind in errors)
    failed = sorted(gate.gate_kind for gate in required if gate.outcome == "FAIL")
    if failed:
        return "REJECT", tuple(f"{kind}_FAIL" for kind in failed)
    pending = sorted(
        gate.gate_kind for gate in required
        if gate.outcome in {"WAIT", "ABSTAIN", "NOT_APPLICABLE", "NOT_EVALUABLE"}
    )
    if pending:
        return "ABSTAIN", tuple(
            f"{kind}_{gates[kind].outcome}" for kind in pending
        )
    if any(gate.outcome != "PASS" for gate in required):
        raise ValueError("unsupported required gate outcome")
    return "ACCEPT", ()


def _candidate_refs(capture, candidate, label_group_refs=()) -> list[dict]:
    refs = [{"kind": "SNAPSHOT", "ref": capture["snapshot_id"]}]
    refs.extend(
        {"kind": "FACT", "ref": fact_id}
        for fact_id in json.loads(candidate["evidence_refs_json"])
    )
    refs.extend(
        {"kind": "LABEL_GROUP", "ref": group_id}
        for group_id in label_group_refs
    )
    return refs


def _gate_semantic(
    store,
    capture,
    candidate,
    gate: GateResult,
    *,
    extra_semantic: object | None = None,
) -> dict:
    semantic = {
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
    if extra_semantic is not None:
        semantic["source_semantic"] = extra_semantic
    return semantic


def _insert_pending_gate(
    store,
    *,
    context,
    capture,
    candidate,
    gate_kind: str,
) -> tuple[GateResult, str]:
    evaluator_version, outcome, reason_code = _PENDING_GATES[gate_kind]
    gate = GateResult.create(
        ctx_id=context["ctx_id"],
        candidate_id=candidate["candidate_id"],
        gate_kind=gate_kind,
        evaluator_version_id=evaluator_version,
        input_refs=_candidate_refs(capture, candidate),
        outcome=outcome,
        reason_code=reason_code,
        error_code=None,
        measurements=[],
        taint=int(combine_taint(context["taint"], candidate["taint"])),
    )
    insert_exact(store.conn, "gate_results", "gate_id", gate)
    digest = _insert_evaluation_member(
        store,
        context["ctx_id"],
        "GATE",
        gate.gate_id,
        _gate_semantic(store, capture, candidate, gate),
    )
    return gate, digest


def _load_h4_correction_sources(
    store, *, context, capture
) -> tuple[bool, tuple[dict, ...]]:
    pin_id = context["label_pin_id"]
    if pin_id is None:
        return False, ()

    pin = store.conn.execute(
        "SELECT * FROM label_set_pins WHERE pin_id=?", (pin_id,)
    ).fetchone()
    if pin is None:
        raise ValueError("evaluation context label pin is missing")
    group_ids = tuple(json.loads(pin["group_ids_json"]))
    if not group_ids:
        return True, ()

    placeholders = ",".join("?" for _ in group_ids)
    rows = store.conn.execute(
        f"""SELECT g.*,s.timeframe,s.instrument_id,s.dataset_id,
                   s.visible_data_cutoff_us AS task_cutoff_us,
                   CASE WHEN z.aggregate_id IS NULL THEN 0 ELSE 1 END AS is_sealed
            FROM label_groups g
            JOIN label_tasks t ON t.task_id=g.task_id
            JOIN label_task_seeds s ON s.seed_id=t.seed_id
            LEFT JOIN sys_seals z
              ON z.aggregate_kind='label_groups'
             AND z.aggregate_id=g.group_id
            WHERE g.group_id IN ({placeholders})
              AND s.timeframe='H4'
              AND s.instrument_id=?
              AND s.dataset_id=?
              AND s.visible_data_cutoff_us<=?
              AND g.visible_data_cutoff_us<=?
              AND (
                ?<>'OPERATIONAL'
                OR (
                  g.label_mode='OPERATIONAL'
                  AND g.operational_available_at_us<=?
                )
              )
            ORDER BY g.group_id""",
        (
            *group_ids,
            capture["instrument_id"],
            capture["dataset_id"],
            capture["decision_time_us"],
            capture["decision_time_us"],
            pin["view_kind"],
            capture["decision_time_us"],
        ),
    ).fetchall()

    if any(not row["is_sealed"] for row in rows):
        raise ValueError("pinned H4 label group must be sealed")

    sources = []
    for row in rows:
        primary_row = store.conn.execute(
            """SELECT rank,probability_ppm,trend,confidence,
                      correction_depth_ppm,correction_class,reason
               FROM label_interpretations
               WHERE group_id=? AND rank=1""",
            (row["group_id"],),
        ).fetchone()
        primary = dict(primary_row) if primary_row is not None else None
        semantic = {
            "group_id": row["group_id"],
            "kind": row["kind"],
            "label_mode": row["label_mode"],
            "view_kind": pin["view_kind"],
            "selector_policy_version": pin["selector_policy_version"],
            "timeframe": row["timeframe"],
            "instrument_id": row["instrument_id"],
            "task_cutoff_us": row["task_cutoff_us"],
            "group_taint": row["taint"],
            "primary": primary,
        }
        sources.append(
            {
                "group_id": row["group_id"],
                "kind": row["kind"],
                "taint": row["taint"],
                "primary": primary,
                "semantic": semantic,
            }
        )
    return True, tuple(sources)


def _insert_correction_location_gate(
    store,
    *,
    context,
    capture,
    candidate,
) -> tuple[GateResult, str]:
    pin_present, sources = _load_h4_correction_sources(
        store, context=context, capture=capture
    )
    measured = evaluate_correction_location(
        sources, label_pin_present=pin_present
    )
    taints = [context["taint"], candidate["taint"]]
    taints.extend(source["taint"] for source in sources)
    gate = GateResult.create(
        ctx_id=context["ctx_id"],
        candidate_id=candidate["candidate_id"],
        gate_kind="CORRECTION_LOCATION",
        evaluator_version_id="p1-correction-location-label-v1",
        input_refs=_candidate_refs(
            capture, candidate, measured.label_group_refs
        ),
        outcome="NOT_APPLICABLE",
        reason_code=measured.reason_code,
        error_code=None,
        measurements=list(measured.measurements),
        taint=int(combine_taint(*taints)),
    )
    insert_exact(store.conn, "gate_results", "gate_id", gate)
    digest = _insert_evaluation_member(
        store,
        context["ctx_id"],
        "GATE",
        gate.gate_id,
        _gate_semantic(
            store,
            capture,
            candidate,
            gate,
            extra_semantic={
                "label_pin_present": pin_present,
                "h4_sources": list(measured.source_semantic),
            },
        ),
    )
    return gate, digest


def _load_c0_gate(store, *, ctx_id: str, candidate_id: str):
    gate = store.conn.execute(
        """SELECT * FROM gate_results
           WHERE ctx_id=? AND candidate_id=? AND gate_kind='DATA_QUALITY'
             AND evaluator_version_id='c0-data-quality-v1'""",
        (ctx_id, candidate_id),
    ).fetchone()
    if gate is None:
        raise ValueError("C0 DATA_QUALITY gate missing")
    digest = store.conn.execute(
        """SELECT content_digest FROM evaluation_unit_members
           WHERE ctx_id=? AND member_kind='GATE' AND member_id=?""",
        (ctx_id, gate["gate_id"]),
    ).fetchone()
    if digest is None:
        raise ValueError("C0 DATA_QUALITY gate evidence missing")
    return GateResult(**dict(gate)), digest[0]


def _insert_owner_arm(
    store,
    *,
    context,
    candidate,
    strategy: StrategyVersion,
    gates: dict[str, GateResult],
    gate_digests: dict[str, str],
) -> ArmResult:
    roles = json.loads(strategy.gate_roles_json)
    gate_refs = [
        {"gate_id": gates[item["gate_kind"]].gate_id, "role": item["role"]}
        for item in roles
    ]
    decision, reasons = _decision_from_required(gates, strategy)
    arm_taint = int(combine_taint(*(gate.taint for gate in gates.values())))
    arm = ArmResult.create(
        candidate_id=candidate["candidate_id"],
        strategy_version_id=strategy.strategy_version_id,
        ctx_id=context["ctx_id"],
        gate_refs=gate_refs,
        decision=decision,
        reason_codes=reasons,
        plan=json.loads(strategy.plan_json),
        taint=arm_taint,
    )
    insert_exact(store.conn, "arm_results", "arm_id", arm)
    arm_semantic = {
        "occurrence_key": candidate["occurrence_key"],
        "strategy_key": strategy.strategy_key,
        "strategy_version": strategy.version,
        "gate_content_digests": [
            gate_digests[item["gate_kind"]]
            for item in roles
        ],
        "decision": arm.decision,
        "reason_codes": json.loads(arm.reason_codes_json),
        "plan": json.loads(arm.plan_json),
        "taint": arm.taint,
    }
    _insert_evaluation_member(
        store, context["ctx_id"], "ARM", arm.arm_id, arm_semantic
    )
    return arm


def _owner_strategies() -> tuple[StrategyVersion, ...]:
    return (
        owner_track_a_strategy(),
        owner_track_a_strategy(break_even_enabled=False),
    )


def _existing_owner_arms(
    store, *, ctx_id: str, strategies: tuple[StrategyVersion, ...]
) -> tuple[ArmResult, ...]:
    if len(strategies) != 2:
        raise ValueError("P1 Track A requires baseline and no-BE strategies")
    rows = store.conn.execute(
        """SELECT a.* FROM arm_results a
           JOIN candidates c ON c.candidate_id=a.candidate_id
           WHERE a.ctx_id=? AND a.strategy_version_id IN (?,?)
           ORDER BY c.occurrence_key,c.candidate_id,
                    CASE a.strategy_version_id WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END""",
        (
            ctx_id,
            strategies[0].strategy_version_id,
            strategies[1].strategy_version_id,
            strategies[0].strategy_version_id,
            strategies[1].strategy_version_id,
        ),
    ).fetchall()
    return tuple(ArmResult(**dict(row)) for row in rows)


def evaluate_p1_track_a(store, *, ctx_id: str) -> P1EvaluationResult:
    """Evaluate C0 plus owner Track A research arms, then seal once."""
    context, capture = _load_context_capture(store, ctx_id)
    c0 = c0_strategy()
    owner_strategies = _owner_strategies()
    sealed = store.conn.execute(
        """SELECT 1 FROM sys_seals
           WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=?""",
        (ctx_id,),
    ).fetchone()
    if sealed:
        candidate_count = store.conn.execute(
            """SELECT count(*) FROM evaluation_contexts x
               JOIN capture_unit_members m
                 ON m.capture_unit_id=x.capture_unit_id
                AND m.member_kind='CANDIDATE'
               WHERE x.ctx_id=?""",
            (ctx_id,),
        ).fetchone()[0]
        c0_arms = _existing_strategy_arms(store, ctx_id=ctx_id, strategy=c0)
        owner_arms = _existing_owner_arms(
            store, ctx_id=ctx_id, strategies=owner_strategies
        )
        if (
            len(c0_arms) != candidate_count
            or len(owner_arms) != candidate_count * len(owner_strategies)
        ):
            raise ValueError(
                "sealed evaluation context does not contain complete P1 Track A arms"
            )
        return P1EvaluationResult(tuple(c0_arms), owner_arms)


    with store.transaction():
        c0_arms = _evaluate_c0_unsealed(
            store, context=context, capture=capture
        )
        for strategy in owner_strategies:
            insert_exact(
                store.conn,
                "strategy_versions",
                "strategy_version_id",
                strategy,
            )

        candidates = store.conn.execute(
            """SELECT c.*
               FROM capture_unit_members m
               JOIN candidates c ON c.candidate_id=m.member_id
               WHERE m.capture_unit_id=? AND m.member_kind='CANDIDATE'
               ORDER BY c.occurrence_key,c.candidate_id""",
            (capture["capture_unit_id"],),
        ).fetchall()
        owner_arms: list[ArmResult] = []
        for candidate in candidates:
            c0_gate, c0_digest = _load_c0_gate(
                store,
                ctx_id=context["ctx_id"],
                candidate_id=candidate["candidate_id"],
            )
            gates = {"DATA_QUALITY": c0_gate}
            gate_digests = {"DATA_QUALITY": c0_digest}
            for gate_kind in _PENDING_GATES:
                gate, digest = _insert_pending_gate(
                    store,
                    context=context,
                    capture=capture,
                    candidate=candidate,
                    gate_kind=gate_kind,
                )
                gates[gate_kind] = gate
                gate_digests[gate_kind] = digest

            correction_gate, correction_digest = _insert_correction_location_gate(
                store,
                context=context,
                capture=capture,
                candidate=candidate,
            )
            gates["CORRECTION_LOCATION"] = correction_gate
            gate_digests["CORRECTION_LOCATION"] = correction_digest

            for strategy in owner_strategies:
                owner_arms.append(
                    _insert_owner_arm(
                        store,
                        context=context,
                        candidate=candidate,
                        strategy=strategy,
                        gates=gates,
                        gate_digests=gate_digests,
                    )
                )

        store.seal_current_transaction("evaluation_contexts", ctx_id)
        return P1EvaluationResult(tuple(c0_arms), tuple(owner_arms))
