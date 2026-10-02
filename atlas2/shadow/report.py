"""Deterministic read-only Shadow report over sealed Atlas v2 evidence."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from atlas2.core.canonical import canonical_json_text
from atlas2.core.taint import Taint, combine_taint
from atlas2.replay.digest import replay_digest_for_store

_DECISIONS = ("ACCEPT", "REJECT", "ABSTAIN", "NOT_ELIGIBLE", "ERROR")


def _connect_read_only(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _taint_names(value: int) -> list[str]:
    flags = combine_taint(value)
    return [
        flag.name for flag in Taint
        if flag is not Taint.NONE and flags & flag
    ]


def _manifest_replay_digest(conn: sqlite3.Connection, manifest_id: str) -> str:
    return replay_digest_for_store(SimpleNamespace(conn=conn), manifest_id)


def _strategy_summaries(
    conn: sqlite3.Connection, ctx_id: str
) -> list[dict]:
    rows = conn.execute(
        """SELECT s.strategy_version_id,s.strategy_key,s.version,
                  a.decision,a.reason_codes_json,a.taint,
                  c.occurrence_key,c.source_detector_id,c.source_detector_version,
                  c.entry_reference_price,c.structural_invalidation_price,
                  c.features_json,c.confidence_ppm,c.taint AS candidate_taint
           FROM arm_results a
           JOIN strategy_versions s
             ON s.strategy_version_id=a.strategy_version_id
           JOIN candidates c ON c.candidate_id=a.candidate_id
           WHERE a.ctx_id=?
           ORDER BY s.strategy_key,s.version,s.strategy_version_id,
                    c.occurrence_key,c.source_detector_id,c.source_detector_version,
                    c.entry_reference_price,c.structural_invalidation_price,
                    c.features_json,c.confidence_ppm,c.taint,a.decision,a.reason_codes_json""",
        (ctx_id,),
    ).fetchall()

    groups: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (
            row["strategy_key"],
            row["version"],
            row["strategy_version_id"],
        )
        group = groups.get(key)
        if group is None:
            group = {
                "strategy_key": row["strategy_key"],
                "strategy_version": row["version"],
                "strategy_version_id": row["strategy_version_id"],
                "arm_count": 0,
                "decisions": {name: 0 for name in _DECISIONS},
                "taint_union": 0,
                "arms": [],
            }
            groups[key] = group
        group["arm_count"] += 1
        group["decisions"][row["decision"]] += 1
        group["taint_union"] |= int(row["taint"])
        group["arms"].append({
            "occurrence_key": row["occurrence_key"],
            "source_detector_id": row["source_detector_id"],
            "source_detector_version": row["source_detector_version"],
            "entry_reference_price": row["entry_reference_price"],
            "structural_invalidation_price": row["structural_invalidation_price"],
            "features": json.loads(row["features_json"]),
            "confidence_ppm": row["confidence_ppm"],
            "candidate_taint": int(row["candidate_taint"]),
            "decision": row["decision"],
            "reason_codes": json.loads(row["reason_codes_json"]),
            "taint": int(row["taint"]),
            "taint_names": _taint_names(int(row["taint"])),
        })

    output = []
    for key in sorted(groups):
        group = groups[key]
        group["taint_names"] = _taint_names(group["taint_union"])
        output.append(group)
    return output


def build_shadow_report(
    db_path: str | Path, manifest_id: str
) -> dict:
    """Build a deterministic report without mutating Atlas evidence."""
    conn = _connect_read_only(db_path)
    try:
        conn.execute("BEGIN")
        digest = _manifest_replay_digest(conn, manifest_id)
        rows = conn.execute(
            """SELECT x.ctx_id,x.capture_unit_id,x.label_pin_id,
                      x.macro_view_class,x.mode,x.taint,
                      u.dataset_id,u.instrument_id,u.decision_time_us,
                      es.child_set_digest AS evaluation_seal_digest,
                      cs.child_set_digest AS capture_seal_digest
               FROM run_aggregate_refs r
               JOIN evaluation_contexts x ON x.ctx_id=r.aggregate_id
               JOIN capture_units u ON u.capture_unit_id=x.capture_unit_id
               JOIN run_aggregate_refs rc
                 ON rc.manifest_id=r.manifest_id
                AND rc.aggregate_kind='capture_units'
                AND rc.aggregate_id=x.capture_unit_id
               JOIN sys_seals es
                 ON es.aggregate_kind='evaluation_contexts'
                AND es.aggregate_id=x.ctx_id
               JOIN sys_seals cs
                 ON cs.aggregate_kind='capture_units'
                AND cs.aggregate_id=x.capture_unit_id
               WHERE r.manifest_id=?
                 AND r.aggregate_kind='evaluation_contexts'
               ORDER BY x.ctx_id""",
            (manifest_id,),
        ).fetchall()
        expected_context_count = conn.execute(
            """SELECT count(*) FROM run_aggregate_refs
               WHERE manifest_id=? AND aggregate_kind='evaluation_contexts'""",
            (manifest_id,),
        ).fetchone()[0]
        if len(rows) != expected_context_count:
            raise ValueError(
                "manifest evaluation context lacks confirmed capture unit"
            )

        contexts = []
        for row in rows:
            candidate_count = conn.execute(
                """SELECT count(*) FROM capture_unit_members
                   WHERE capture_unit_id=? AND member_kind='CANDIDATE'""",
                (row["capture_unit_id"],),
            ).fetchone()[0]
            strategies = _strategy_summaries(conn, row["ctx_id"])
            arm_count = sum(item["arm_count"] for item in strategies)
            arm_taint_union = 0
            for item in strategies:
                arm_taint_union |= item["taint_union"]
            contexts.append({
                "ctx_id": row["ctx_id"],
                "capture_unit_id": row["capture_unit_id"],
                "dataset_id": row["dataset_id"],
                "instrument_id": row["instrument_id"],
                "decision_time_us": row["decision_time_us"],
                "mode": row["mode"],
                "macro_view_class": row["macro_view_class"],
                "label_pin_id": row["label_pin_id"],
                "candidate_count": candidate_count,
                "arm_count": arm_count,
                "context_taint": int(row["taint"]),
                "context_taint_names": _taint_names(int(row["taint"])),
                "arm_taint_union": arm_taint_union,
                "arm_taint_names": _taint_names(arm_taint_union),
                "evaluation_seal_digest": row["evaluation_seal_digest"],
                "capture_seal_digest": row["capture_seal_digest"],
                "strategies": strategies,
            })

        return {
            "schema": "ATLAS2_SHADOW_REPORT_V1",
            "surface": "SHADOW_REPLAY_READ_ONLY",
            "authority": "NO_ORDER",
            "owner_strategy_status": "NOT_IMPLEMENTED",
            "entry_semantics_status": "OWNER_DECISION_PENDING",
            "manifest_id": manifest_id,
            "replay_digest": digest,
            "context_count": len(contexts),
            "contexts": contexts,
        }
    finally:
        conn.close()


def render_shadow_report_json(
    db_path: str | Path, manifest_id: str
) -> str:
    return canonical_json_text(build_shadow_report(db_path, manifest_id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Path to atlas.sqlite3")
    parser.add_argument("manifest_id", help="Run manifest identity")
    args = parser.parse_args(argv)
    print(render_shadow_report_json(args.database, args.manifest_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
