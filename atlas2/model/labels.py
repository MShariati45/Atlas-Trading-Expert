"""Frozen label evidence contracts for Atlas v2 P0-5."""
from __future__ import annotations

from dataclasses import dataclass
import json

from atlas2.core.canonical import canonical_json_text, validate_canonical_json_text
from atlas2.core.ids import make_id, validate_id
from atlas2.core.taint import Taint, combine_taint
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64
from atlas2.model.data import _instrument, _text

BLIND_MODES = frozenset({"NONE", "IDENTITY", "IDENTITY_PRICE"})
GROUP_KINDS = frozenset({"INTERPRETATIONS", "ABSTENTION"})
LABEL_MODES = frozenset({"OPERATIONAL", "RETROSPECTIVE", "LEGACY_IMPORT", "ENGINE"})
TRENDS = frozenset({"BULLISH", "BEARISH", "RANGE", "TRANSITION"})
CORRECTION_CLASSES = frozenset(
    {"MINOR", "MAJOR", "NONE_YET", "UNCLASSIFIED_EQUALITY"}
)
ANCHOR_ROLES = frozenset({"IMPULSE_START", "IMPULSE_END", "CORRECTION_EXTREME"})
ANCHOR_SIDES = frozenset({"HIGH", "LOW"})
TIME_STATUSES = frozenset({"EXACT_BAR", "UNKNOWN_LEGACY", "INFERRED_RECONSTRUCTION"})
VIEW_KINDS = frozenset({"OPERATIONAL", "RESEARCH"})


@dataclass(frozen=True, slots=True)
class LabelTaskSeed:
    seed_id: str
    study_id: str
    instrument_id: str
    timeframe: str
    dataset_id: str
    visible_data_cutoff_us: int
    lookback_bars: int
    blind_mode: str
    repeat_index: int
    include_forming_bar: bool = False

    @classmethod
    def create(
        cls,
        study_id: str,
        instrument_id: str,
        timeframe: str,
        dataset_id: str,
        visible_data_cutoff_us: int,
        lookback_bars: int,
        blind_mode: str,
        repeat_index: int,
    ) -> "LabelTaskSeed":
        payload = {
            "study_id": study_id,
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "dataset_id": dataset_id,
            "visible_data_cutoff_us": visible_data_cutoff_us,
            "lookback_bars": lookback_bars,
            "blind_mode": blind_mode,
            "repeat_index": repeat_index,
            "include_forming_bar": False,
        }
        model = cls(make_id("lseed", "label-task-seed-v1", payload), **payload)
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.seed_id, "lseed")
        _text(self.study_id)
        _instrument(self.instrument_id)
        if self.timeframe not in {"M15", "H1", "H4", "D1"}:
            raise ValueError("invalid label timeframe")
        validate_id(self.dataset_id, "ds")
        validate_utc_micros(self.visible_data_cutoff_us)
        if type(self.lookback_bars) is not int or self.lookback_bars <= 0:
            raise ValueError("lookback_bars must be positive int")
        if self.blind_mode not in BLIND_MODES:
            raise ValueError("invalid blind mode")
        if type(self.repeat_index) is not int or self.repeat_index < 0:
            raise ValueError("repeat_index must be nonnegative int")
        if self.include_forming_bar is not False:
            raise ValueError("P0-5 tasks never include a forming bar")
        expected = make_id(
            "lseed",
            "label-task-seed-v1",
            {
                "study_id": self.study_id,
                "instrument_id": self.instrument_id,
                "timeframe": self.timeframe,
                "dataset_id": self.dataset_id,
                "visible_data_cutoff_us": self.visible_data_cutoff_us,
                "lookback_bars": self.lookback_bars,
                "blind_mode": self.blind_mode,
                "repeat_index": self.repeat_index,
                "include_forming_bar": False,
            },
        )
        if self.seed_id != expected:
            raise ValueError("label task seed identity mismatch")


@dataclass(frozen=True, slots=True)
class LabelTask:
    task_id: str
    seed_id: str
    transform_json: str

    @classmethod
    def create(cls, seed_id: str, transform: object) -> "LabelTask":
        transform_json = canonical_json_text(transform)
        model = cls(
            make_id(
                "ltask",
                "label-task-v1",
                {"seed_id": seed_id, "transform": json.loads(transform_json)},
            ),
            seed_id,
            transform_json,
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.task_id, "ltask")
        validate_id(self.seed_id, "lseed")
        validate_canonical_json_text(self.transform_json)
        expected = make_id(
            "ltask",
            "label-task-v1",
            {"seed_id": self.seed_id, "transform": json.loads(self.transform_json)},
        )
        if self.task_id != expected:
            raise ValueError("label task identity mismatch")


@dataclass(frozen=True, slots=True)
class LabelSubmissionGroup:
    group_id: str
    task_id: str
    labeler_id: str
    request_key: str
    kind: str
    label_mode: str
    submitted_at_us: int
    visible_data_cutoff_us: int
    operational_available_at_us: int | None
    supersedes_group_id: str | None
    revision_reason: str | None
    abstention_reason: str | None
    exposure_attestation: str
    system_exposure_flag: bool
    taint: int

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        labeler_id: str,
        request_key: str,
        kind: str,
        label_mode: str,
        submitted_at_us: int,
        visible_data_cutoff_us: int,
        supersedes_group_id: str | None,
        revision_reason: str | None,
        abstention_reason: str | None,
        exposure_attestation: str,
        system_exposure_flag: bool,
        extra_taint: int = 0,
    ) -> "LabelSubmissionGroup":
        taint = Taint(extra_taint)
        if label_mode == "RETROSPECTIVE":
            taint |= Taint.RETRO_LABEL
        if label_mode == "LEGACY_IMPORT":
            taint |= Taint.INFERRED_RECONSTRUCTION
        operational = submitted_at_us if label_mode == "OPERATIONAL" else None
        model = cls(
            make_id(
                "lgrp",
                "label-group-v1",
                [task_id, labeler_id, request_key],
            ),
            task_id,
            labeler_id,
            request_key,
            kind,
            label_mode,
            submitted_at_us,
            visible_data_cutoff_us,
            operational,
            supersedes_group_id,
            revision_reason,
            abstention_reason,
            exposure_attestation,
            system_exposure_flag,
            int(taint),
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.group_id, "lgrp")
        validate_id(self.task_id, "ltask")
        _text(self.labeler_id)
        _text(self.request_key)
        if self.kind not in GROUP_KINDS:
            raise ValueError("invalid label group kind")
        if self.label_mode not in LABEL_MODES:
            raise ValueError("invalid label mode")
        validate_utc_micros(self.submitted_at_us)
        validate_utc_micros(self.visible_data_cutoff_us)
        if self.submitted_at_us < self.visible_data_cutoff_us:
            raise ValueError("label cannot be submitted before its visible-data cutoff")
        if self.label_mode == "OPERATIONAL":
            if self.operational_available_at_us != self.submitted_at_us:
                raise ValueError("operational label availability must equal submission time")
        elif self.operational_available_at_us is not None:
            raise ValueError("non-operational label cannot have operational availability")
        if self.supersedes_group_id is not None:
            validate_id(self.supersedes_group_id, "lgrp")
            if self.revision_reason is None:
                raise ValueError("revision reason required")
        elif self.revision_reason is not None:
            raise ValueError("revision reason requires supersedes_group_id")
        if self.revision_reason is not None:
            _text(self.revision_reason)
        if self.kind == "ABSTENTION":
            if self.abstention_reason is None:
                raise ValueError("abstention reason required")
            _text(self.abstention_reason)
        elif self.abstention_reason is not None:
            raise ValueError("abstention reason is only valid for ABSTENTION")
        _text(self.exposure_attestation)
        if type(self.system_exposure_flag) is not bool:
            raise TypeError("system_exposure_flag must be bool")
        combine_taint(self.taint)
        required = 0
        if self.label_mode == "RETROSPECTIVE":
            required |= int(Taint.RETRO_LABEL)
        if self.label_mode == "LEGACY_IMPORT":
            required |= int(Taint.INFERRED_RECONSTRUCTION)
        if self.taint & required != required:
            raise ValueError("label mode required taint is missing")
        expected = make_id(
            "lgrp",
            "label-group-v1",
            [self.task_id, self.labeler_id, self.request_key],
        )
        if self.group_id != expected:
            raise ValueError("label group identity mismatch")


@dataclass(frozen=True, slots=True)
class Interpretation:
    interpretation_id: str
    group_id: str
    rank: int
    probability_ppm: int | None
    trend: str
    confidence: int
    correction_depth_ppm: int | None
    correction_class: str | None
    reason: str | None

    @classmethod
    def create(
        cls,
        *,
        group_id: str,
        rank: int,
        probability_ppm: int | None,
        trend: str,
        confidence: int,
        correction_depth_ppm: int | None,
        correction_class: str | None,
        reason: str | None,
    ) -> "Interpretation":
        payload = {
            "group_id": group_id,
            "rank": rank,
            "probability_ppm": probability_ppm,
            "trend": trend,
            "confidence": confidence,
            "correction_depth_ppm": correction_depth_ppm,
            "correction_class": correction_class,
            "reason": reason,
        }
        model = cls(make_id("lint", "label-interpretation-v1", payload), **payload)
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.interpretation_id, "lint")
        validate_id(self.group_id, "lgrp")
        if type(self.rank) is not int or not 1 <= self.rank <= 3:
            raise ValueError("interpretation rank must be 1..3")
        if self.probability_ppm is not None:
            validate_int64(self.probability_ppm)
            if not 0 <= self.probability_ppm <= 1_000_000:
                raise ValueError("probability_ppm out of range")
        if self.trend not in TRENDS:
            raise ValueError("invalid trend")
        if type(self.confidence) is not int or not 1 <= self.confidence <= 5:
            raise ValueError("confidence must be 1..5")
        if self.correction_depth_ppm is not None:
            validate_int64(self.correction_depth_ppm)
            if self.correction_depth_ppm < 0:
                raise ValueError("correction depth cannot be negative")
        if (
            self.correction_class is not None
            and self.correction_class not in CORRECTION_CLASSES
        ):
            raise ValueError("invalid correction class")
        if self.reason is not None:
            _text(self.reason)
        expected = make_id(
            "lint",
            "label-interpretation-v1",
            {
                "group_id": self.group_id,
                "rank": self.rank,
                "probability_ppm": self.probability_ppm,
                "trend": self.trend,
                "confidence": self.confidence,
                "correction_depth_ppm": self.correction_depth_ppm,
                "correction_class": self.correction_class,
                "reason": self.reason,
            },
        )
        if self.interpretation_id != expected:
            raise ValueError("interpretation identity mismatch")


@dataclass(frozen=True, slots=True)
class Anchor:
    anchor_id: str
    interpretation_id: str
    role: str
    bar_open_time_us: int | None
    side: str
    price: int
    confirmation_time_us: int | None
    time_status: str

    @classmethod
    def create(
        cls,
        *,
        interpretation_id: str,
        role: str,
        bar_open_time_us: int | None,
        side: str,
        price: int,
        confirmation_time_us: int | None,
        time_status: str,
    ) -> "Anchor":
        payload = {
            "interpretation_id": interpretation_id,
            "role": role,
            "bar_open_time_us": bar_open_time_us,
            "side": side,
            "price": price,
            "confirmation_time_us": confirmation_time_us,
            "time_status": time_status,
        }
        model = cls(make_id("lanch", "label-anchor-v1", payload), **payload)
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.anchor_id, "lanch")
        validate_id(self.interpretation_id, "lint")
        if self.role not in ANCHOR_ROLES:
            raise ValueError("invalid anchor role")
        if self.side not in ANCHOR_SIDES:
            raise ValueError("invalid anchor side")
        validate_int64(self.price)
        if self.time_status not in TIME_STATUSES:
            raise ValueError("invalid anchor time status")
        if self.time_status == "UNKNOWN_LEGACY":
            if self.bar_open_time_us is not None or self.confirmation_time_us is not None:
                raise ValueError("UNKNOWN_LEGACY anchor must not claim exact times")
        else:
            if self.bar_open_time_us is None:
                raise ValueError("timed anchor requires bar_open_time_us")
            validate_utc_micros(self.bar_open_time_us)
            if self.confirmation_time_us is not None:
                validate_utc_micros(self.confirmation_time_us)
        expected = make_id(
            "lanch",
            "label-anchor-v1",
            {
                "interpretation_id": self.interpretation_id,
                "role": self.role,
                "bar_open_time_us": self.bar_open_time_us,
                "side": self.side,
                "price": self.price,
                "confirmation_time_us": self.confirmation_time_us,
                "time_status": self.time_status,
            },
        )
        if self.anchor_id != expected:
            raise ValueError("anchor identity mismatch")


@dataclass(frozen=True, slots=True)
class LabelSetPin:
    pin_id: str
    view_kind: str
    group_ids: tuple[str, ...]
    selector_policy_version: str
    taint: int

    @classmethod
    def create(
        cls,
        *,
        view_kind: str,
        group_ids: tuple[str, ...],
        selector_policy_version: str,
        taint: int,
    ) -> "LabelSetPin":
        groups = tuple(sorted(group_ids))
        payload = {
            "view_kind": view_kind,
            "group_ids": list(groups),
            "selector_policy_version": selector_policy_version,
        }
        model = cls(
            make_id("lpin", "label-set-pin-v1", payload),
            view_kind,
            groups,
            selector_policy_version,
            taint,
        )
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.pin_id, "lpin")
        if self.view_kind not in VIEW_KINDS:
            raise ValueError("invalid label view kind")
        if type(self.group_ids) is not tuple:
            raise TypeError("group_ids must be tuple")
        if self.group_ids != tuple(sorted(set(self.group_ids))):
            raise ValueError("group_ids must be sorted and unique")
        for group_id in self.group_ids:
            validate_id(group_id, "lgrp")
        _text(self.selector_policy_version)
        combine_taint(self.taint)
        expected = make_id(
            "lpin",
            "label-set-pin-v1",
            {
                "view_kind": self.view_kind,
                "group_ids": list(self.group_ids),
                "selector_policy_version": self.selector_policy_version,
            },
        )
        if self.pin_id != expected:
            raise ValueError("label set pin identity mismatch")
