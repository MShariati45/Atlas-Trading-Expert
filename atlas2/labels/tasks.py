"""Causal label-task creation for Atlas v2 P0-5."""
from __future__ import annotations

import hashlib
import hmac

from atlas2.model.labels import LabelTask, LabelTaskSeed
from atlas2.research.holdout import guard_read
from atlas2.store.repository import Store, StoreConflict, ConflictKind

_FRAME_US = {
    "M15": 15 * 60 * 1_000_000,
    "H1": 60 * 60 * 1_000_000,
    "H4": 4 * 60 * 60 * 1_000_000,
    "D1": 24 * 60 * 60 * 1_000_000,
}


def blind_transform(seed: LabelTaskSeed, study_secret: bytes | None) -> dict:
    seed.validate()
    if seed.blind_mode == "NONE":
        return {}
    if seed.blind_mode == "IDENTITY":
        return {"hide_identity": True}
    if study_secret is None or not isinstance(study_secret, bytes) or not study_secret:
        raise ValueError("IDENTITY_PRICE requires a nonempty study secret")
    digest = hmac.new(study_secret, seed.seed_id.encode("ascii"), hashlib.sha256).hexdigest()
    return {"hide_identity": True, "price_transform_seed_hmac_sha256": digest}


class LabelTaskService:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    def create(
        self,
        *,
        study_id: str,
        instrument_id: str,
        timeframe: str,
        dataset_id: str,
        visible_data_cutoff_us: int,
        lookback_bars: int,
        blind_mode: str,
        repeat_index: int,
        actor: str,
        purpose: str,
        grant_ids: tuple[str, ...] = (),
        request_key_prefix: str = "label-task",
        study_secret: bytes | None = None,
    ) -> tuple[LabelTaskSeed, LabelTask]:
        seed = LabelTaskSeed.create(
            study_id,
            instrument_id,
            timeframe,
            dataset_id,
            visible_data_cutoff_us,
            lookback_bars,
            blind_mode,
            repeat_index,
        )
        if not self.conn.execute(
            "SELECT 1 FROM data_datasets WHERE dataset_id=?", (dataset_id,)
        ).fetchone():
            raise ValueError("unknown dataset")
        span = _FRAME_US[timeframe]
        start_us = visible_data_cutoff_us - lookback_bars * span
        guard_read(
            self.store,
            instrument_id=instrument_id,
            start_us=start_us,
            end_us=visible_data_cutoff_us,
            route="LABEL_TASK",
            actor=actor,
            purpose=purpose,
            grant_ids=grant_ids,
            request_key_prefix=f"{request_key_prefix}:{seed.seed_id}",
        )
        task = LabelTask.create(seed.seed_id, blind_transform(seed, study_secret))
        with self.store.transaction():
            seed_row = self.conn.execute(
                "SELECT * FROM label_task_seeds WHERE seed_id=?", (seed.seed_id,)
            ).fetchone()
            if seed_row is None:
                self.conn.execute(
                    "INSERT INTO label_task_seeds VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        seed.seed_id,
                        seed.study_id,
                        seed.instrument_id,
                        seed.timeframe,
                        seed.dataset_id,
                        seed.visible_data_cutoff_us,
                        seed.lookback_bars,
                        seed.blind_mode,
                        seed.repeat_index,
                        0,
                    ),
                )
            else:
                expected = {
                    "seed_id": seed.seed_id,
                    "study_id": seed.study_id,
                    "instrument_id": seed.instrument_id,
                    "timeframe": seed.timeframe,
                    "dataset_id": seed.dataset_id,
                    "visible_data_cutoff_us": seed.visible_data_cutoff_us,
                    "lookback_bars": seed.lookback_bars,
                    "blind_mode": seed.blind_mode,
                    "repeat_index": seed.repeat_index,
                    "include_forming_bar": 0,
                }
                if dict(seed_row) != expected:
                    raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)

            task_row = self.conn.execute(
                "SELECT * FROM label_tasks WHERE task_id=?", (task.task_id,)
            ).fetchone()
            if task_row is None:
                self.conn.execute(
                    "INSERT INTO label_tasks VALUES (?,?,?)",
                    (task.task_id, task.seed_id, task.transform_json),
                )
            elif dict(task_row) != {
                "task_id": task.task_id,
                "seed_id": task.seed_id,
                "transform_json": task.transform_json,
            }:
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        return seed, task
