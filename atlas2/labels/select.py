"""Operational/research label selection and immutable LabelSetPin evidence."""
from __future__ import annotations

import json

from atlas2.core.canonical import canonical_json_text
from atlas2.core.taint import combine_taint
from atlas2.model.labels import LabelSetPin
from atlas2.store.repository import Store, StoreConflict, ConflictKind

POLICIES = frozenset({"per-labeler-latest-v1", "latest-authorized-owner-v1"})


class LabelSelectionService:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    def _eligible(
        self,
        *,
        task_id: str,
        view_kind: str,
        as_of_us: int,
        authorized_labelers: tuple[str, ...],
    ):
        if view_kind not in {"OPERATIONAL", "RESEARCH"}:
            raise ValueError("invalid label view kind")
        if not authorized_labelers:
            raise ValueError("authorized_labelers cannot be empty")
        placeholders = ",".join("?" for _ in authorized_labelers)
        if view_kind == "OPERATIONAL":
            sql = f"""SELECT * FROM label_groups
                      WHERE task_id=?
                        AND labeler_id IN ({placeholders})
                        AND label_mode='OPERATIONAL'
                        AND operational_available_at_us<=?
                        AND visible_data_cutoff_us<=?
                      ORDER BY labeler_id,submitted_at_us DESC,group_id DESC"""
            params = (task_id, *authorized_labelers, as_of_us, as_of_us)
        else:
            sql = f"""SELECT * FROM label_groups
                      WHERE task_id=?
                        AND labeler_id IN ({placeholders})
                        AND submitted_at_us<=?
                      ORDER BY labeler_id,submitted_at_us DESC,group_id DESC"""
            params = (task_id, *authorized_labelers, as_of_us)
        return self.conn.execute(sql, params).fetchall()

    def select(
        self,
        *,
        task_id: str,
        view_kind: str,
        as_of_us: int,
        authorized_labelers: tuple[str, ...],
        selector_policy_version: str,
    ) -> LabelSetPin:
        if selector_policy_version not in POLICIES:
            raise ValueError("unknown selector policy")
        if not self.conn.execute(
            "SELECT 1 FROM label_tasks WHERE task_id=?", (task_id,)
        ).fetchone():
            raise ValueError("unknown label task")

        rows = self._eligible(
            task_id=task_id,
            view_kind=view_kind,
            as_of_us=as_of_us,
            authorized_labelers=authorized_labelers,
        )
        latest_by_labeler = {}
        for row in rows:
            latest_by_labeler.setdefault(row["labeler_id"], row)
        selected = list(latest_by_labeler.values())
        if selector_policy_version == "latest-authorized-owner-v1" and selected:
            selected = [
                max(
                    selected,
                    key=lambda row: (
                        row["submitted_at_us"],
                        row["labeler_id"],
                        row["group_id"],
                    ),
                )
            ]

        group_ids = tuple(sorted(row["group_id"] for row in selected))
        taint = int(combine_taint(*(row["taint"] for row in selected)))
        pin = LabelSetPin.create(
            view_kind=view_kind,
            group_ids=group_ids,
            selector_policy_version=selector_policy_version,
            taint=taint,
        )
        group_ids_json = canonical_json_text(list(pin.group_ids))
        with self.store.transaction():
            row = self.conn.execute(
                "SELECT * FROM label_set_pins WHERE pin_id=?", (pin.pin_id,)
            ).fetchone()
            expected = {
                "pin_id": pin.pin_id,
                "view_kind": pin.view_kind,
                "group_ids_json": group_ids_json,
                "selector_policy_version": pin.selector_policy_version,
                "taint": pin.taint,
            }
            if row is None:
                self.conn.execute(
                    "INSERT INTO label_set_pins VALUES (?,?,?,?,?)",
                    tuple(expected.values()),
                )
            elif dict(row) != expected:
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        return pin

    def groups_for_pin(self, pin_id: str):
        row = self.conn.execute(
            "SELECT * FROM label_set_pins WHERE pin_id=?", (pin_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown label set pin")
        group_ids = json.loads(row["group_ids_json"])
        if not group_ids:
            return []
        placeholders = ",".join("?" for _ in group_ids)
        return self.conn.execute(
            f"SELECT * FROM label_groups WHERE group_id IN ({placeholders}) "
            "ORDER BY group_id",
            group_ids,
        ).fetchall()
