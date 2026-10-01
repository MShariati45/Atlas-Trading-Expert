"""Atomic label submission groups and revisions for Atlas v2 P0-5."""
from __future__ import annotations

from dataclasses import asdict
import sqlite3

from atlas2.core.taint import Taint
from atlas2.model.labels import (
    Anchor,
    Interpretation,
    LabelSubmissionGroup,
)
from atlas2.store.repository import Store

_FRAME_US = {
    "M15": 15 * 60 * 1_000_000,
    "H1": 60 * 60 * 1_000_000,
    "H4": 4 * 60 * 60 * 1_000_000,
    "D1": 24 * 60 * 60 * 1_000_000,
}


class LabelSubmissionService:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    def _task_context(self, task_id: str):
        row = self.conn.execute(
            """SELECT t.task_id,s.timeframe,s.visible_data_cutoff_us
               FROM label_tasks t
               JOIN label_task_seeds s ON s.seed_id=t.seed_id
               WHERE t.task_id=?""",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown label task")
        return row

    def _current_group(self, task_id: str, labeler_id: str):
        return self.conn.execute(
            """SELECT g.*
               FROM label_groups g
               WHERE g.task_id=? AND g.labeler_id=?
                 AND NOT EXISTS(
                   SELECT 1 FROM label_groups child
                   WHERE child.supersedes_group_id=g.group_id
                 )
               ORDER BY g.submitted_at_us DESC,g.group_id DESC
               LIMIT 1""",
            (task_id, labeler_id),
        ).fetchone()

    @staticmethod
    def _validate_interpretation_spec(specs: list[dict]) -> None:
        if not 1 <= len(specs) <= 3:
            raise ValueError("INTERPRETATIONS group requires 1..3 interpretations")
        ranks = [spec["rank"] for spec in specs]
        if len(set(ranks)) != len(ranks):
            raise ValueError("interpretation ranks must be unique")
        total = sum(
            spec["probability_ppm"]
            for spec in specs
            if spec.get("probability_ppm") is not None
        )
        if total > 1_000_000:
            raise ValueError("probability_ppm total exceeds 1,000,000")

    @staticmethod
    def _validate_anchors(
        anchors: list[Anchor],
        *,
        timeframe: str,
        cutoff_us: int,
    ) -> None:
        roles = [anchor.role for anchor in anchors]
        if len(set(roles)) != len(roles):
            raise ValueError("anchor roles must be unique within interpretation")
        span = _FRAME_US[timeframe]
        for anchor in anchors:
            anchor.validate()
            if anchor.time_status == "UNKNOWN_LEGACY":
                continue
            close_us = anchor.bar_open_time_us + span
            if close_us > cutoff_us:
                raise ValueError("anchor bar must be complete by visible cutoff")
            if anchor.confirmation_time_us is not None:
                if anchor.confirmation_time_us < close_us:
                    raise ValueError("anchor confirmation cannot precede bar close")
                if anchor.confirmation_time_us > cutoff_us:
                    raise ValueError("anchor confirmation exceeds visible cutoff")

    def submit(
        self,
        *,
        task_id: str,
        labeler_id: str,
        request_key: str,
        kind: str,
        label_mode: str,
        interpretations: list[dict] | None = None,
        abstention_reason: str | None = None,
        supersedes_group_id: str | None = None,
        revision_reason: str | None = None,
        exposure_attestation: str = "DECLARED",
        system_exposure_flag: bool = False,
        extra_taint: int = 0,
    ) -> LabelSubmissionGroup:
        task = self._task_context(task_id)
        specs = [] if interpretations is None else list(interpretations)
        if kind == "INTERPRETATIONS":
            self._validate_interpretation_spec(specs)
            if abstention_reason is not None:
                raise ValueError("interpretation group cannot carry abstention reason")
        elif kind == "ABSTENTION":
            if specs:
                raise ValueError("abstention group cannot carry interpretations")
            if not abstention_reason:
                raise ValueError("abstention reason required")
        else:
            raise ValueError("invalid label group kind")

        # Pre-build child payload shapes, but submission time/group ID are created atomically.
        payload = {
            "task_id": task_id,
            "kind": kind,
            "label_mode": label_mode,
            "interpretations": specs,
            "abstention_reason": abstention_reason,
            "supersedes_group_id": supersedes_group_id,
            "revision_reason": revision_reason,
            "exposure_attestation": exposure_attestation,
            "system_exposure_flag": system_exposure_flag,
            "extra_taint": extra_taint,
        }

        def write(submitted_at_us: int) -> str:
            current = self._current_group(task_id, labeler_id)
            if current is None:
                if supersedes_group_id is not None:
                    raise ValueError("cannot revise missing prior label group")
            else:
                if supersedes_group_id != current["group_id"]:
                    raise ValueError("revision must supersede current prior group")

            child_taint = int(extra_taint)
            if any(
                anchor.get("time_status") == "INFERRED_RECONSTRUCTION"
                for spec in specs
                for anchor in spec.get("anchors", [])
            ):
                child_taint |= int(Taint.INFERRED_RECONSTRUCTION)

            group = LabelSubmissionGroup.create(
                task_id=task_id,
                labeler_id=labeler_id,
                request_key=request_key,
                kind=kind,
                label_mode=label_mode,
                submitted_at_us=submitted_at_us,
                visible_data_cutoff_us=task["visible_data_cutoff_us"],
                supersedes_group_id=supersedes_group_id,
                revision_reason=revision_reason,
                abstention_reason=abstention_reason,
                exposure_attestation=exposure_attestation,
                system_exposure_flag=system_exposure_flag,
                extra_taint=child_taint,
            )
            values = asdict(group)
            values["system_exposure_flag"] = int(group.system_exposure_flag)
            self.conn.execute(
                """INSERT INTO label_groups(
                   group_id,task_id,labeler_id,request_key,kind,label_mode,
                   submitted_at_us,visible_data_cutoff_us,operational_available_at_us,
                   supersedes_group_id,revision_reason,abstention_reason,
                   exposure_attestation,system_exposure_flag,taint
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(values.values()),
            )

            for spec in sorted(specs, key=lambda item: item["rank"]):
                interpretation = Interpretation.create(
                    group_id=group.group_id,
                    rank=spec["rank"],
                    probability_ppm=spec.get("probability_ppm"),
                    trend=spec["trend"],
                    confidence=spec["confidence"],
                    correction_depth_ppm=spec.get("correction_depth_ppm"),
                    correction_class=spec.get("correction_class"),
                    reason=spec.get("reason"),
                )
                self.conn.execute(
                    """INSERT INTO label_interpretations(
                       interpretation_id,group_id,rank,probability_ppm,trend,confidence,
                       correction_depth_ppm,correction_class,reason
                       ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    tuple(asdict(interpretation).values()),
                )
                anchors = [
                    Anchor.create(
                        interpretation_id=interpretation.interpretation_id,
                        role=anchor["role"],
                        bar_open_time_us=anchor.get("bar_open_time_us"),
                        side=anchor["side"],
                        price=anchor["price"],
                        confirmation_time_us=anchor.get("confirmation_time_us"),
                        time_status=anchor["time_status"],
                    )
                    for anchor in spec.get("anchors", [])
                ]
                self._validate_anchors(
                    anchors,
                    timeframe=task["timeframe"],
                    cutoff_us=task["visible_data_cutoff_us"],
                )
                for anchor in anchors:
                    self.conn.execute(
                        """INSERT INTO label_anchors(
                           anchor_id,interpretation_id,role,bar_open_time_us,side,price,
                           confirmation_time_us,time_status
                           ) VALUES (?,?,?,?,?,?,?,?)""",
                        tuple(asdict(anchor).values()),
                    )

            self.store.seal_current_transaction("label_groups", group.group_id)
            return group.group_id

        receipt = self.store.request_write(
            labeler_id,
            "labels.submit",
            f"{task_id}:{request_key}",
            payload,
            write,
        )
        row = self.conn.execute(
            "SELECT * FROM label_groups WHERE group_id=?", (receipt.result_ref,)
        ).fetchone()
        if row is None:
            raise RuntimeError("label submission receipt is inconsistent")
        data = dict(row)
        data["system_exposure_flag"] = bool(data["system_exposure_flag"])
        return LabelSubmissionGroup(**data)
