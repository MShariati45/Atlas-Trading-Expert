"""Semantic replay projection used by determinism and cross-dataset tests."""
from __future__ import annotations

import json


def project_context(store, ctx_id: str) -> list[dict]:
    ctx = store.conn.execute(
        "SELECT * FROM evaluation_contexts WHERE ctx_id=?", (ctx_id,)
    ).fetchone()
    if ctx is None:
        raise ValueError("unknown evaluation context")
    unit = store.conn.execute(
        "SELECT * FROM capture_units WHERE capture_unit_id=?", (ctx["capture_unit_id"],)
    ).fetchone()
    snapshot = store.conn.execute(
        "SELECT visible_fact_digest FROM market_snapshots WHERE snapshot_id=?",
        (unit["snapshot_id"],),
    ).fetchone()
    rows = store.conn.execute(
        """SELECT c.* FROM capture_unit_members m
           JOIN candidates c ON c.candidate_id=m.member_id
           WHERE m.capture_unit_id=? AND m.member_kind='CANDIDATE'
           ORDER BY c.occurrence_key,c.candidate_id""",
        (unit["capture_unit_id"],),
    ).fetchall()
    output = []
    for candidate in rows:
        detection = store.conn.execute(
            """SELECT r.raw_payload_json,e.status AS invocation_status,e.error_code
               FROM candidates c
               JOIN raw_detection_receipts r ON r.receipt_id=c.receipt_id
               JOIN detector_invocation_ends e ON e.invocation_id=r.invocation_id
               WHERE c.candidate_id=?""",
            (candidate["candidate_id"],),
        ).fetchone()
        raw_payload = json.loads(detection["raw_payload_json"])
        gates = [
            {
                "kind": row["gate_kind"],
                "evaluator_version": row["evaluator_version_id"],
                "outcome": row["outcome"],
                "reason": row["reason_code"],
                "error": row["error_code"],
                "measurements": json.loads(row["measurements_json"]),
            }
            for row in store.conn.execute(
                "SELECT * FROM gate_results WHERE ctx_id=? AND candidate_id=? "
                "ORDER BY gate_kind,evaluator_version_id,gate_id",
                (ctx_id, candidate["candidate_id"]),
            )
        ]
        arms = [
            {
                "strategy_key": row["strategy_key"],
                "strategy_version": row["version"],
                "decision": row["decision"],
                "reason_codes": json.loads(row["reason_codes_json"]),
                "plan": json.loads(row["plan_json"]),
            }
            for row in store.conn.execute(
                """SELECT a.*,s.strategy_key,s.version
                   FROM arm_results a
                   JOIN strategy_versions s ON s.strategy_version_id=a.strategy_version_id
                   WHERE a.ctx_id=? AND a.candidate_id=?
                   ORDER BY s.strategy_key,s.version,a.arm_id""",
                (ctx_id, candidate["candidate_id"]),
            )
        ]
        output.append({
            "instrument": candidate["instrument_id"],
            "decision_time_us": unit["decision_time_us"],
            "occurrence_key": candidate["occurrence_key"],
            "detector_version": candidate["source_detector_version"],
            "invocation_status": detection["invocation_status"],
            "invocation_error": detection["error_code"],
            "receipt_status": raw_payload.get("status"),
            "receipt_reasons": raw_payload.get("reason_codes", []),
            "candidate_geometry": {
                "entry_reference_price": candidate["entry_reference_price"],
                "structural_invalidation_price": candidate["structural_invalidation_price"],
                "features": json.loads(candidate["features_json"]),
            },
            "visible_fact_digest": snapshot[0],
            "gates": gates,
            "arms": arms,
        })
    return output
