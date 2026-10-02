"""Directed candidate relation persistence for one evaluation context."""
from __future__ import annotations

from dataclasses import asdict

from atlas2.core.canonical import domain_digest
from atlas2.core.taint import combine_taint
from atlas2.model.evaluation import CandidateRelation
from atlas2.evaluate.ledger import identity_conflict


def add_relation(
    store,
    *,
    ctx_id: str,
    relation_kind: str,
    evaluator_version_id: str,
    primary_candidate_id: str,
    other_candidate_id: str,
    taint: int = 0,
) -> CandidateRelation:
    context = store.conn.execute(
        "SELECT taint FROM evaluation_contexts WHERE ctx_id=?", (ctx_id,)
    ).fetchone()
    primary = store.conn.execute(
        "SELECT occurrence_key,taint FROM candidates WHERE candidate_id=?",
        (primary_candidate_id,),
    ).fetchone()
    other = store.conn.execute(
        "SELECT occurrence_key,taint FROM candidates WHERE candidate_id=?",
        (other_candidate_id,),
    ).fetchone()
    if context is None or primary is None or other is None:
        raise ValueError("unknown relation context/candidate")
    inherited_taint = int(combine_taint(context["taint"], primary["taint"], other["taint"], taint))
    model = CandidateRelation.create(
        ctx_id=ctx_id,
        relation_kind=relation_kind,
        evaluator_version_id=evaluator_version_id,
        primary_candidate_id=primary_candidate_id,
        other_candidate_id=other_candidate_id,
        taint=inherited_taint,
    )
    semantic = {
        "relation_kind": relation_kind,
        "evaluator_version_id": evaluator_version_id,
        "primary_occurrence_key": primary[0],
        "other_occurrence_key": other[0],
        "taint": inherited_taint,
    }
    with store.transaction():
        row = store.conn.execute(
            "SELECT * FROM candidate_relations WHERE relation_id=?", (model.relation_id,)
        ).fetchone()
        if row is None:
            store.conn.execute(
                "INSERT INTO candidate_relations VALUES (?,?,?,?,?,?,?)",
                tuple(asdict(model).values()),
            )
            store.conn.execute(
                "INSERT INTO evaluation_unit_members VALUES (?,?,?,?)",
                (ctx_id, "RELATION", model.relation_id, domain_digest("evaluation-member-v1", semantic)),
            )
        elif dict(row) != asdict(model):
            raise identity_conflict()
    return model
