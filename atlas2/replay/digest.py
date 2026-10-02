"""Deterministic replay digest over the frozen aggregate allowlist."""
from __future__ import annotations

import hashlib

_KIND_LABEL = {
    "capture_units": "CAPTURE_UNIT",
    "evaluation_contexts": "EVALUATION_UNIT",
    "outcome_batches": "OUTCOME_BATCH",
    "portfolio_scenarios": "PORTFOLIO_SCENARIO",
}


def replay_digest(seals) -> str:
    lines = []
    for kind, aggregate_id, child_set_digest in seals:
        label = _KIND_LABEL.get(kind)
        if label is None:
            continue
        lines.append(f"{label}\t{aggregate_id}\t{child_set_digest}")
    h = hashlib.sha256()
    for line in sorted(lines):
        h.update(line.encode("utf-8") + b"\n")
    return h.hexdigest()


def confirm_aggregate(store, manifest_id: str, aggregate_kind: str, aggregate_id: str) -> None:
    if aggregate_kind not in {"capture_units", "evaluation_contexts", "outcome_batches"}:
        raise ValueError("aggregate kind is not replay-digest eligible")
    if not store.conn.execute(
        "SELECT 1 FROM run_manifests WHERE manifest_id=?", (manifest_id,)
    ).fetchone():
        raise ValueError("unknown run manifest")
    with store.transaction():
        row = store.conn.execute(
            "SELECT 1 FROM run_aggregate_refs WHERE manifest_id=? AND aggregate_kind=? AND aggregate_id=?",
            (manifest_id, aggregate_kind, aggregate_id),
        ).fetchone()
        if row is None:
            store.conn.execute(
                "INSERT INTO run_aggregate_refs VALUES (?,?,?)",
                (manifest_id, aggregate_kind, aggregate_id),
            )


def replay_digest_for_store(store, manifest_id: str | None = None) -> str:
    if manifest_id is None:
        rows = store.conn.execute(
            "SELECT aggregate_kind,aggregate_id,child_set_digest FROM sys_seals "
            "WHERE aggregate_kind IN ('capture_units','evaluation_contexts','outcome_batches') "
            "ORDER BY aggregate_kind,aggregate_id"
        ).fetchall()
    else:
        if not store.conn.execute(
            "SELECT 1 FROM run_manifests WHERE manifest_id=?", (manifest_id,)
        ).fetchone():
            raise ValueError("unknown run manifest")
        rows = store.conn.execute(
            """SELECT r.aggregate_kind,r.aggregate_id,s.child_set_digest
               FROM run_aggregate_refs r
               JOIN sys_seals s
                 ON s.aggregate_kind=r.aggregate_kind AND s.aggregate_id=r.aggregate_id
               WHERE r.manifest_id=?
               ORDER BY r.aggregate_kind,r.aggregate_id""",
            (manifest_id,),
        ).fetchall()
    return replay_digest((row[0], row[1], row[2]) for row in rows)
