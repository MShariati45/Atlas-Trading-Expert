"""Candidate-first immutable detection contracts for Atlas v2 P0-6."""
from __future__ import annotations

from dataclasses import dataclass
import json

from atlas2.core.canonical import canonical_json_text, validate_canonical_json_text
from atlas2.core.ids import make_id, validate_id
from atlas2.core.taint import combine_taint
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64
from atlas2.model.data import _instrument, _text

DIRECTIONS = frozenset({"LONG", "SHORT"})
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "ABORTED"})


def canonical_evidence_refs(refs) -> tuple[str, ...]:
    if isinstance(refs, (str, bytes)):
        raise ValueError("evidence_refs must be an ID collection, not text/bytes")
    values = tuple(sorted(refs))
    if values != tuple(sorted(set(values))):
        raise ValueError("evidence_refs must be unique")
    for ref in values:
        validate_id(ref, ("fbar", "fqt"))
    return values


def canonical_anchors(anchors) -> tuple[tuple[str, int], ...]:
    result = []
    for anchor in anchors:
        if type(anchor) is not dict or set(anchor) != {"role", "time_us"}:
            raise ValueError("occurrence anchors must contain only role + time_us")
        _text(anchor["role"])
        validate_utc_micros(anchor["time_us"])
        result.append((anchor["role"], anchor["time_us"]))
    result = tuple(sorted(result))
    if result != tuple(sorted(set(result))):
        raise ValueError("occurrence anchors must be unique")
    return result


def make_occurrence_key(
    *,
    instrument_id: str,
    timeframe: str,
    pattern_family: str,
    direction: str,
    trigger_time_us: int,
    anchors,
) -> str:
    _instrument(instrument_id)
    if timeframe != "M15":
        raise ValueError("P0-6 candidate capture is M15")
    _text(pattern_family)
    if direction not in DIRECTIONS:
        raise ValueError("direction must be LONG/SHORT")
    validate_utc_micros(trigger_time_us)
    canonical = canonical_anchors(anchors)
    return make_id(
        "occ",
        "candidate-occurrence-v1",
        {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "pattern_family": pattern_family,
            "direction": direction,
            "trigger_time_us": trigger_time_us,
            "anchors": [{"role": role, "time_us": time_us} for role, time_us in canonical],
        },
    )


@dataclass(frozen=True, slots=True)
class DetectorInvocation:
    invocation_id: str
    run_attempt_id: str
    dataset_id: str
    detector_id: str
    detector_version: str
    instrument_id: str
    timeframe: str
    as_of_us: int
    parameters_json: str

    @classmethod
    def create(
        cls, *, run_attempt_id: str, dataset_id: str, detector_id: str,
        detector_version: str, instrument_id: str, timeframe: str,
        as_of_us: int, parameters: object,
    ) -> "DetectorInvocation":
        parameters_json = canonical_json_text(parameters)
        payload = {
            "run_attempt_id": run_attempt_id,
            "dataset_id": dataset_id,
            "detector_id": detector_id,
            "detector_version": detector_version,
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "as_of_us": as_of_us,
            "parameters": json.loads(parameters_json),
        }
        model = cls(make_id("dinv", "detector-invocation-v1", payload),
                    run_attempt_id, dataset_id, detector_id, detector_version,
                    instrument_id, timeframe, as_of_us, parameters_json)
        model.validate()
        return model

    def validate(self) -> None:
        validate_id(self.invocation_id, "dinv")
        _text(self.run_attempt_id)
        validate_id(self.dataset_id, "ds")
        _text(self.detector_id); _text(self.detector_version)
        _instrument(self.instrument_id)
        if self.timeframe != "M15":
            raise ValueError("P0-6 detector invocation must be M15")
        validate_utc_micros(self.as_of_us)
        validate_canonical_json_text(self.parameters_json)
        expected = make_id(
            "dinv", "detector-invocation-v1",
            {"run_attempt_id": self.run_attempt_id, "dataset_id": self.dataset_id,
             "detector_id": self.detector_id, "detector_version": self.detector_version,
             "instrument_id": self.instrument_id, "timeframe": self.timeframe,
             "as_of_us": self.as_of_us, "parameters": json.loads(self.parameters_json)}
        )
        if self.invocation_id != expected:
            raise ValueError("detector invocation identity mismatch")


@dataclass(frozen=True, slots=True)
class RawDetectionReceipt:
    receipt_id: str
    invocation_id: str
    receipt_index: int
    occurrence_key: str
    instrument_id: str
    timeframe: str
    pattern_family: str
    direction: str
    trigger_time_us: int
    detected_at_us: int
    available_at_us: int
    anchors_json: str
    raw_payload_json: str
    evidence_refs_json: str
    source_detector_id: str
    source_detector_version: str
    taint: int
    recorded_at_us: int

    def validate(self) -> None:
        validate_id(self.receipt_id, "rdet")
        validate_id(self.invocation_id, "dinv")
        if type(self.receipt_index) is not int or self.receipt_index < 1:
            raise ValueError("receipt_index must be positive")
        validate_id(self.occurrence_key, "occ")
        _instrument(self.instrument_id)
        if self.timeframe != "M15":
            raise ValueError("raw detection must be M15")
        _text(self.pattern_family)
        if self.direction not in DIRECTIONS:
            raise ValueError("direction must be LONG/SHORT")
        for value in (self.trigger_time_us, self.detected_at_us, self.available_at_us, self.recorded_at_us):
            validate_utc_micros(value)
        if not self.trigger_time_us <= self.detected_at_us <= self.available_at_us:
            raise ValueError("raw detection timing is non-causal")
        validate_canonical_json_text(self.anchors_json)
        validate_canonical_json_text(self.raw_payload_json)
        validate_canonical_json_text(self.evidence_refs_json)
        anchors = json.loads(self.anchors_json)
        refs = json.loads(self.evidence_refs_json)
        canonical = canonical_anchors(anchors)
        if any(time_us > self.detected_at_us for _, time_us in canonical):
            raise ValueError("occurrence anchor is after detection time")
        canonical_evidence_refs(refs)
        _text(self.source_detector_id); _text(self.source_detector_version)
        combine_taint(self.taint)
        expected_occ = make_occurrence_key(
            instrument_id=self.instrument_id, timeframe=self.timeframe,
            pattern_family=self.pattern_family, direction=self.direction,
            trigger_time_us=self.trigger_time_us, anchors=anchors,
        )
        if self.occurrence_key != expected_occ:
            raise ValueError("occurrence identity mismatch")
        expected = make_id(
            "rdet", "raw-detection-receipt-v1",
            {"invocation_id": self.invocation_id, "receipt_index": self.receipt_index,
             "occurrence_key": self.occurrence_key,
             "detected_at_us": self.detected_at_us, "available_at_us": self.available_at_us,
             "anchors": anchors, "raw_payload": json.loads(self.raw_payload_json),
             "evidence_refs": refs, "taint": self.taint},
        )
        if self.receipt_id != expected:
            raise ValueError("raw detection receipt identity mismatch")


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    receipt_id: str
    occurrence_key: str
    instrument_id: str
    timeframe: str
    pattern_family: str
    direction: str
    trigger_time_us: int
    detected_at_us: int
    available_at_us: int
    entry_reference_price: int | None
    structural_invalidation_price: int | None
    features_json: str
    confidence_ppm: int | None
    evidence_refs_json: str
    source_detector_id: str
    source_detector_version: str
    taint: int
    normalized_at_us: int

    def validate(self) -> None:
        validate_id(self.candidate_id, "cand")
        validate_id(self.receipt_id, "rdet"); validate_id(self.occurrence_key, "occ")
        _instrument(self.instrument_id)
        if self.timeframe != "M15": raise ValueError("candidate must be M15")
        _text(self.pattern_family)
        if self.direction not in DIRECTIONS: raise ValueError("direction must be LONG/SHORT")
        for value in (self.trigger_time_us, self.detected_at_us, self.available_at_us, self.normalized_at_us):
            validate_utc_micros(value)
        if not self.trigger_time_us <= self.detected_at_us <= self.available_at_us:
            raise ValueError("candidate timing is non-causal")
        for value in (self.entry_reference_price, self.structural_invalidation_price):
            if value is not None: validate_int64(value)
        validate_canonical_json_text(self.features_json)
        validate_canonical_json_text(self.evidence_refs_json)
        canonical_evidence_refs(json.loads(self.evidence_refs_json))
        if self.confidence_ppm is not None:
            validate_int64(self.confidence_ppm)
            if not 0 <= self.confidence_ppm <= 1_000_000:
                raise ValueError("confidence_ppm out of range")
        _text(self.source_detector_id); _text(self.source_detector_version)
        combine_taint(self.taint)
        expected = make_id(
            "cand", "candidate-v1",
            {"receipt_id": self.receipt_id, "occurrence_key": self.occurrence_key,
             "entry_reference_price": self.entry_reference_price,
             "structural_invalidation_price": self.structural_invalidation_price,
             "features": json.loads(self.features_json),
             "confidence_ppm": self.confidence_ppm},
        )
        if self.candidate_id != expected:
            raise ValueError("candidate identity mismatch")


@dataclass(frozen=True, slots=True)
class DetectorInvocationEnd:
    invocation_id: str
    status: str
    receipt_count: int
    candidate_count: int
    error_code: str | None
    ended_at_us: int

    def validate(self) -> None:
        validate_id(self.invocation_id, "dinv")
        if self.status not in TERMINAL_STATUSES: raise ValueError("invalid terminal status")
        for value in (self.receipt_count, self.candidate_count):
            validate_int64(value)
            if value < 0: raise ValueError("counts cannot be negative")
        if self.status == "COMPLETED" and self.receipt_count != self.candidate_count:
            raise ValueError("COMPLETED requires one candidate per receipt")
        if self.error_code is not None: _text(self.error_code)
        validate_utc_micros(self.ended_at_us)
