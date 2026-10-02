"""Snapshot, sealed capture-unit, and EvaluationContext creation."""
from __future__ import annotations

from dataclasses import asdict
import json

from atlas2.core.canonical import canonical_json_text, domain_digest
from atlas2.core.enums import RunMode, ViewClass
from atlas2.core.taint import combine_taint
from atlas2.data.views import MarketView
from atlas2.model.evaluation import CaptureUnit, EvaluationContext, MarketSnapshot
from atlas2.evaluate.ledger import identity_conflict, insert_exact

_FRAME_US = {
    "M15": 15 * 60 * 1_000_000,
    "H1": 60 * 60 * 1_000_000,
    "H4": 4 * 60 * 60 * 1_000_000,
    "D1": 24 * 60 * 60 * 1_000_000,
}



def build_snapshot(
    store,
    *,
    dataset_id: str,
    instrument_id: str,
    as_of_us: int,
    windows,
    view_class: str = "PIT",
    mode: str = "REPLAY",
    actor: str = "replay",
    purpose: str = "evaluation",
    grant_ids: tuple[str, ...] = (),
) -> MarketSnapshot:
    normalized = []
    visible_ids: set[str] = set()
    taints = []
    market = MarketView(
        store,
        dataset_id,
        mode=RunMode(mode),
        actor=actor,
        purpose=purpose,
        grant_ids=grant_ids,
        request_key_prefix=f"snapshot:{dataset_id}:{instrument_id}:{as_of_us}",
    )
    for window in windows:
        if type(window) is not dict:
            raise ValueError("snapshot window must be a dict")
        timeframe = window.get("timeframe")
        lookback = window.get("lookback")
        price_side = window.get("price_side", "BID")
        include_partial = window.get("include_partial", False)
        if timeframe not in _FRAME_US:
            raise ValueError("unsupported snapshot timeframe")
        if type(lookback) is not int or lookback <= 0:
            raise ValueError("snapshot lookback must be positive")
        if include_partial is not False:
            raise ValueError("P0-7 snapshots exclude partial bars")
        start_us = as_of_us - lookback * _FRAME_US[timeframe]
        bars = market.bars(
            instrument_id,
            timeframe,
            price_side,
            start_us,
            as_of_us,
            as_of_us,
            view_class=ViewClass(view_class),
        )
        visible_ids.update(bar.fact.fact_id for bar in bars)
        taints.extend(bar.taint for bar in bars)
        normalized.append({
            "timeframe": timeframe,
            "lookback": lookback,
            "include_partial": False,
            "price_side": price_side,
        })
    normalized.sort(key=canonical_json_text)
    model = MarketSnapshot.create(
        dataset_id=dataset_id,
        instrument_id=instrument_id,
        as_of_us=as_of_us,
        view_class=view_class,
        mode=mode,
        windows=normalized,
        visible_fact_ids=visible_ids,
        taint=int(combine_taint(*taints)),
    )
    with store.transaction():
        insert_exact(store.conn, "market_snapshots", "snapshot_id", model)
    return model


def _semantic_capture(store, *, dataset_id: str, instrument_id: str, decision_time_us: int, snapshot_id: str):
    invocations = store.conn.execute(
        """SELECT * FROM detector_invocations
           WHERE dataset_id=? AND instrument_id=? AND as_of_us=?
           ORDER BY detector_id,detector_version,invocation_id""",
        (dataset_id, instrument_id, decision_time_us),
    ).fetchall()
    if not invocations:
        raise ValueError("capture unit requires at least one detector invocation")

    semantic_invocations = []
    semantic_ends = []
    semantic_receipts = []
    semantic_candidates = []
    members = [("SNAPSHOT", snapshot_id, domain_digest(
        "capture-member-v1",
        {"kind": "SNAPSHOT", "snapshot_id": snapshot_id},
    ))]
    candidate_ids = []

    for inv in invocations:
        end = store.conn.execute(
            "SELECT * FROM detector_invocation_ends WHERE invocation_id=?",
            (inv["invocation_id"],),
        ).fetchone()
        if end is None:
            raise ValueError("all detector invocations must be terminal before capture seal")
        inv_sem = {
            "detector_id": inv["detector_id"],
            "detector_version": inv["detector_version"],
            "instrument_id": inv["instrument_id"],
            "timeframe": inv["timeframe"],
            "as_of_us": inv["as_of_us"],
            "parameters": json.loads(inv["parameters_json"]),
        }
        semantic_invocations.append(inv_sem)
        members.append(("INVOCATION", inv["invocation_id"], domain_digest(
            "capture-member-v1", {"kind": "INVOCATION", "value": inv_sem}
        )))
        end_sem = {
            "detector_id": inv["detector_id"],
            "detector_version": inv["detector_version"],
            "status": end["status"],
            "receipt_count": end["receipt_count"],
            "candidate_count": end["candidate_count"],
            "error_code": end["error_code"],
        }
        semantic_ends.append(end_sem)
        members.append(("INVOCATION_END", inv["invocation_id"], domain_digest(
            "capture-member-v1", {"kind": "INVOCATION_END", "value": end_sem}
        )))

        receipts = store.conn.execute(
            "SELECT * FROM raw_detection_receipts WHERE invocation_id=? ORDER BY receipt_index,receipt_id",
            (inv["invocation_id"],),
        ).fetchall()
        for receipt in receipts:
            receipt_sem = {
                "detector_id": inv["detector_id"],
                "detector_version": inv["detector_version"],
                "receipt_index": receipt["receipt_index"],
                "occurrence_key": receipt["occurrence_key"],
                "instrument_id": receipt["instrument_id"],
                "timeframe": receipt["timeframe"],
                "pattern_family": receipt["pattern_family"],
                "direction": receipt["direction"],
                "trigger_time_us": receipt["trigger_time_us"],
                "detected_at_us": receipt["detected_at_us"],
                "available_at_us": receipt["available_at_us"],
                "anchors": json.loads(receipt["anchors_json"]),
                "raw_payload": json.loads(receipt["raw_payload_json"]),
                "evidence_refs": json.loads(receipt["evidence_refs_json"]),
                "taint": receipt["taint"],
            }
            semantic_receipts.append(receipt_sem)
            members.append(("RECEIPT", receipt["receipt_id"], domain_digest(
                "capture-member-v1", {"kind": "RECEIPT", "value": receipt_sem}
            )))
            candidate = store.conn.execute(
                "SELECT * FROM candidates WHERE receipt_id=?", (receipt["receipt_id"],)
            ).fetchone()
            if candidate is not None:
                cand_sem = {
                    "occurrence_key": candidate["occurrence_key"],
                    "instrument_id": candidate["instrument_id"],
                    "timeframe": candidate["timeframe"],
                    "pattern_family": candidate["pattern_family"],
                    "direction": candidate["direction"],
                    "trigger_time_us": candidate["trigger_time_us"],
                    "detected_at_us": candidate["detected_at_us"],
                    "available_at_us": candidate["available_at_us"],
                    "entry_reference_price": candidate["entry_reference_price"],
                    "structural_invalidation_price": candidate["structural_invalidation_price"],
                    "features": json.loads(candidate["features_json"]),
                    "confidence_ppm": candidate["confidence_ppm"],
                    "evidence_refs": json.loads(candidate["evidence_refs_json"]),
                    "source_detector_id": candidate["source_detector_id"],
                    "source_detector_version": candidate["source_detector_version"],
                    "taint": candidate["taint"],
                }
                semantic_candidates.append(cand_sem)
                candidate_ids.append(candidate["candidate_id"])
                members.append(("CANDIDATE", candidate["candidate_id"], domain_digest(
                    "capture-member-v1", {"kind": "CANDIDATE", "value": cand_sem}
                )))

    projection = {
        "snapshot_id": snapshot_id,
        "invocations": sorted(semantic_invocations, key=canonical_json_text),
        "ends": sorted(semantic_ends, key=canonical_json_text),
        "receipts": sorted(semantic_receipts, key=canonical_json_text),
        "candidates": sorted(semantic_candidates, key=canonical_json_text),
    }
    return domain_digest("capture-semantic-v1", projection), tuple(sorted(candidate_ids)), tuple(members)


def seal_capture_unit(
    store,
    *,
    dataset_id: str,
    instrument_id: str,
    decision_time_us: int,
    snapshot_id: str,
) -> CaptureUnit:
    snapshot = store.conn.execute(
        "SELECT * FROM market_snapshots WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    if snapshot is None:
        raise ValueError("unknown market snapshot")
    if (
        snapshot["dataset_id"] != dataset_id
        or snapshot["instrument_id"] != instrument_id
        or snapshot["as_of_us"] != decision_time_us
    ):
        raise ValueError("snapshot does not match capture unit")
    semantic_digest, candidate_ids, members = _semantic_capture(
        store,
        dataset_id=dataset_id,
        instrument_id=instrument_id,
        decision_time_us=decision_time_us,
        snapshot_id=snapshot_id,
    )
    model = CaptureUnit.create(
        dataset_id=dataset_id,
        instrument_id=instrument_id,
        decision_time_us=decision_time_us,
        snapshot_id=snapshot_id,
        candidate_ids=candidate_ids,
        semantic_capture_digest=semantic_digest,
    )

    with store.transaction():
        existing = store.conn.execute(
            "SELECT * FROM capture_units WHERE capture_unit_id=?", (model.capture_unit_id,)
        ).fetchone()
        if existing is not None:
            if existing["semantic_capture_digest"] != semantic_digest:
                raise identity_conflict()
            seal = store.conn.execute(
                "SELECT child_set_digest FROM sys_seals WHERE aggregate_kind='capture_units' AND aggregate_id=?",
                (model.capture_unit_id,),
            ).fetchone()
            if seal is None:
                raise identity_conflict()
            return CaptureUnit(**dict(existing))

        store.conn.execute(
            "INSERT INTO capture_units VALUES (?,?,?,?,?,?,?)",
            tuple(asdict(model).values()),
        )
        for kind, member_id, content_digest in sorted(members):
            store.conn.execute(
                "INSERT INTO capture_unit_members VALUES (?,?,?,?)",
                (model.capture_unit_id, kind, member_id, content_digest),
            )
        store.seal_current_transaction("capture_units", model.capture_unit_id)
    return model


def create_context(
    store,
    *,
    capture_unit_id: str,
    label_pin_id: str | None,
    macro_view_class: str,
    mode: str,
) -> EvaluationContext:
    capture = store.conn.execute(
        "SELECT * FROM capture_units WHERE capture_unit_id=?", (capture_unit_id,)
    ).fetchone()
    if capture is None:
        raise ValueError("unknown capture unit")
    if not store.conn.execute(
        "SELECT 1 FROM sys_seals WHERE aggregate_kind='capture_units' AND aggregate_id=?",
        (capture_unit_id,),
    ).fetchone():
        raise ValueError("capture unit must be sealed")

    taints = [
        row[0] for row in store.conn.execute(
            """SELECT c.taint FROM capture_unit_members m
               JOIN candidates c ON c.candidate_id=m.member_id
               WHERE m.capture_unit_id=? AND m.member_kind='CANDIDATE'""",
            (capture_unit_id,),
        )
    ]
    snapshot_row = store.conn.execute(
        "SELECT mode,taint FROM market_snapshots WHERE snapshot_id=?", (capture["snapshot_id"],)
    ).fetchone()
    if snapshot_row is None:
        raise ValueError("capture unit snapshot is missing")
    if snapshot_row["mode"] != mode:
        raise ValueError("evaluation mode must match capture snapshot mode")
    taints.append(snapshot_row["taint"])
    if label_pin_id is not None:
        pin = store.conn.execute(
            "SELECT taint FROM label_set_pins WHERE pin_id=?", (label_pin_id,)
        ).fetchone()
        if pin is None:
            raise ValueError("unknown label pin")
        taints.append(pin[0])

    model = EvaluationContext.create(
        capture_unit_id=capture_unit_id,
        label_pin_id=label_pin_id,
        macro_view_class=macro_view_class,
        mode=mode,
        taint=int(combine_taint(*taints)),
    )
    with store.transaction():
        insert_exact(store.conn, "evaluation_contexts", "ctx_id", model)
    return model
