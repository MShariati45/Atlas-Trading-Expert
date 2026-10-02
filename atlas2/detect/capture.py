"""Candidate-first persistence service for Atlas v2 P0-6."""
from __future__ import annotations

from dataclasses import asdict
import json

from atlas2.core.canonical import canonical_json_text
from atlas2.core.ids import make_id
from atlas2.core.taint import combine_taint
from atlas2.model.candidates import (
    Candidate, DetectorInvocation, DetectorInvocationEnd, RawDetectionReceipt,
    canonical_anchors, canonical_evidence_refs, make_occurrence_key,
)
from atlas2.store.repository import ConflictKind, Store, StoreConflict


class CandidateCaptureService:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    def _validate_evidence_visibility(
        self, invocation, evidence_refs: tuple[str, ...], available_at_us: int
    ) -> None:
        mode_row = self.conn.execute(
            """SELECT m.mode FROM run_attempt_starts s
               JOIN run_manifests m ON m.manifest_id=s.manifest_id
               WHERE s.attempt_id=?""",
            (invocation["run_attempt_id"],),
        ).fetchone()
        if mode_row is None:
            raise ValueError("invocation run attempt has no manifest")
        mode = mode_row[0]
        for fact_id in evidence_refs:
            rows = self.conn.execute(
                """SELECT l.available_at_us,l.availability_basis,o.acquired_at_us
                   FROM data_dataset_membership m
                   JOIN data_fact_links l
                     ON l.fact_id=m.fact_id AND l.obs_id=m.obs_id AND l.locator=m.locator
                   JOIN source_observations o ON o.obs_id=m.obs_id
                   WHERE m.dataset_id=? AND m.fact_id=?""",
                (invocation["dataset_id"], fact_id),
            ).fetchall()
            if not rows:
                raise ValueError("evidence ref is not in invocation dataset")
            visible = False
            for row in rows:
                if row["availability_basis"] == "UNKNOWN" or row["available_at_us"] is None:
                    continue
                knowledge_time = row["available_at_us"]
                if mode == "FORWARD":
                    knowledge_time = max(knowledge_time, row["acquired_at_us"])
                if knowledge_time <= available_at_us:
                    visible = True
                    break
            if not visible:
                raise ValueError("evidence ref was not available by receipt availability")

    def start_invocation(self, **kwargs) -> DetectorInvocation:
        model = DetectorInvocation.create(**kwargs)
        with self.store.transaction():
            if not self.conn.execute(
                "SELECT 1 FROM run_attempt_starts WHERE attempt_id=?",
                (model.run_attempt_id,),
            ).fetchone():
                raise ValueError("unknown run attempt")
            if not self.conn.execute(
                "SELECT 1 FROM data_datasets WHERE dataset_id=?",
                (model.dataset_id,),
            ).fetchone():
                raise ValueError("unknown dataset")
            row = self.conn.execute(
                "SELECT * FROM detector_invocations WHERE invocation_id=?",
                (model.invocation_id,),
            ).fetchone()
            expected = asdict(model)
            if row is None:
                self.conn.execute(
                    "INSERT INTO detector_invocations VALUES (?,?,?,?,?,?,?,?,?)",
                    tuple(expected.values()),
                )
            elif dict(row) != expected:
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        return model

    def record_raw(
        self, *, invocation_id: str, receipt_index: int, pattern_family: str,
        direction: str, trigger_time_us: int, detected_at_us: int,
        available_at_us: int, anchors, raw_payload: object, evidence_refs,
        taint: int, actor: str = "detector",
    ) -> RawDetectionReceipt:
        invocation = self.conn.execute(
            "SELECT * FROM detector_invocations WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        if invocation is None:
            raise ValueError("unknown detector invocation")
        anchors_c = canonical_anchors(anchors)
        anchors_obj = [{"role": role, "time_us": time_us} for role, time_us in anchors_c]
        refs = canonical_evidence_refs(evidence_refs)
        self._validate_evidence_visibility(invocation, refs, available_at_us)
        occurrence_key = make_occurrence_key(
            instrument_id=invocation["instrument_id"], timeframe=invocation["timeframe"],
            pattern_family=pattern_family, direction=direction,
            trigger_time_us=trigger_time_us, anchors=anchors_obj,
        )
        raw_payload_json = canonical_json_text(raw_payload)
        anchors_json = canonical_json_text(anchors_obj)
        evidence_refs_json = canonical_json_text(list(refs))
        combine_taint(taint)
        identity = {
            "invocation_id": invocation_id, "receipt_index": receipt_index,
            "occurrence_key": occurrence_key,
            "detected_at_us": detected_at_us, "available_at_us": available_at_us,
            "anchors": anchors_obj, "raw_payload": json.loads(raw_payload_json),
            "evidence_refs": list(refs), "taint": int(taint),
        }
        receipt_id = make_id("rdet", "raw-detection-receipt-v1", identity)
        payload = identity | {
            "pattern_family": pattern_family, "direction": direction,
            "trigger_time_us": trigger_time_us, "detected_at_us": detected_at_us,
            "available_at_us": available_at_us,
        }

        def write(server_time_us: int) -> str:
            model = RawDetectionReceipt(
                receipt_id, invocation_id, receipt_index, occurrence_key,
                invocation["instrument_id"], invocation["timeframe"], pattern_family,
                direction, trigger_time_us, detected_at_us, available_at_us,
                anchors_json, raw_payload_json, evidence_refs_json,
                invocation["detector_id"], invocation["detector_version"],
                int(taint), server_time_us,
            )
            model.validate()
            if model.available_at_us > invocation["as_of_us"]:
                raise ValueError("receipt availability exceeds invocation as_of")
            self.conn.execute(
                """INSERT INTO raw_detection_receipts(
                   receipt_id,invocation_id,receipt_index,occurrence_key,instrument_id,
                   timeframe,pattern_family,direction,trigger_time_us,detected_at_us,
                   available_at_us,anchors_json,raw_payload_json,evidence_refs_json,
                   source_detector_id,source_detector_version,taint,recorded_at_us
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(asdict(model).values()),
            )
            return model.receipt_id

        receipt = self.store.request_write(
            actor, "detect.raw", f"{invocation_id}:{receipt_index}", payload, write
        )
        row = self.conn.execute(
            "SELECT * FROM raw_detection_receipts WHERE receipt_id=?", (receipt.result_ref,)
        ).fetchone()
        return RawDetectionReceipt(**dict(row))

    def normalize_candidate(
        self, *, receipt_id: str, entry_reference_price: int | None,
        structural_invalidation_price: int | None, features: object,
        confidence_ppm: int | None, actor: str = "detector",
    ) -> Candidate:
        raw = self.conn.execute(
            "SELECT * FROM raw_detection_receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone()
        if raw is None:
            raise ValueError("raw receipt must exist before candidate normalization")
        features_json = canonical_json_text(features)
        identity = {
            "receipt_id": receipt_id, "occurrence_key": raw["occurrence_key"],
            "entry_reference_price": entry_reference_price,
            "structural_invalidation_price": structural_invalidation_price,
            "features": json.loads(features_json), "confidence_ppm": confidence_ppm,
        }
        candidate_id = make_id("cand", "candidate-v1", identity)
        payload = identity

        def write(server_time_us: int) -> str:
            model = Candidate(
                candidate_id, raw["receipt_id"], raw["occurrence_key"],
                raw["instrument_id"], raw["timeframe"], raw["pattern_family"],
                raw["direction"], raw["trigger_time_us"], raw["detected_at_us"],
                raw["available_at_us"], entry_reference_price,
                structural_invalidation_price, features_json, confidence_ppm,
                raw["evidence_refs_json"], raw["source_detector_id"],
                raw["source_detector_version"], raw["taint"], server_time_us,
            )
            model.validate()
            self.conn.execute(
                """INSERT INTO candidates(
                   candidate_id,receipt_id,occurrence_key,instrument_id,timeframe,
                   pattern_family,direction,trigger_time_us,detected_at_us,available_at_us,
                   entry_reference_price,structural_invalidation_price,features_json,
                   confidence_ppm,evidence_refs_json,source_detector_id,
                   source_detector_version,taint,normalized_at_us
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(asdict(model).values()),
            )
            return model.candidate_id

        result = self.store.request_write(
            actor, "detect.candidate", receipt_id, payload, write
        )
        row = self.conn.execute(
            "SELECT * FROM candidates WHERE candidate_id=?", (result.result_ref,)
        ).fetchone()
        return Candidate(**dict(row))

    def end_invocation(
        self, invocation_id: str, status: str, *, error_code: str | None = None,
        actor: str = "detector",
    ) -> DetectorInvocationEnd:
        if not self.conn.execute(
            "SELECT 1 FROM detector_invocations WHERE invocation_id=?", (invocation_id,)
        ).fetchone():
            raise ValueError("unknown detector invocation")
        payload = {"invocation_id": invocation_id, "status": status, "error_code": error_code}

        def write(server_time_us: int) -> str:
            receipt_count = self.conn.execute(
                "SELECT count(*) FROM raw_detection_receipts WHERE invocation_id=?",
                (invocation_id,),
            ).fetchone()[0]
            candidate_count = self.conn.execute(
                """SELECT count(*) FROM candidates c JOIN raw_detection_receipts r
                   ON r.receipt_id=c.receipt_id WHERE r.invocation_id=?""",
                (invocation_id,),
            ).fetchone()[0]
            model = DetectorInvocationEnd(
                invocation_id, status, receipt_count, candidate_count,
                error_code, server_time_us,
            )
            model.validate()
            self.conn.execute(
                "INSERT INTO detector_invocation_ends VALUES (?,?,?,?,?,?)",
                tuple(asdict(model).values()),
            )
            return invocation_id

        result = self.store.request_write(
            actor, "detect.end", invocation_id, payload, write
        )
        row = self.conn.execute(
            "SELECT * FROM detector_invocation_ends WHERE invocation_id=?",
            (result.result_ref,),
        ).fetchone()
        return DetectorInvocationEnd(**dict(row))
