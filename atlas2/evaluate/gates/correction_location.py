"""Pure P1 correction-location measurement policy.

Correction depth is H4 context evidence only. It never becomes an entry gate.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorrectionLocationEvaluation:
    reason_code: str
    measurements: tuple[dict, ...]
    label_group_refs: tuple[str, ...]
    source_semantic: tuple[dict, ...]


def evaluate_correction_location(
    sources: tuple[dict, ...],
    *,
    label_pin_present: bool,
) -> CorrectionLocationEvaluation:
    """Measure one pinned H4 source without inventing source aggregation."""
    refs = tuple(sorted(source["group_id"] for source in sources))
    ordered = tuple(sorted(sources, key=lambda item: item["group_id"]))
    semantic = tuple(source["semantic"] for source in ordered)

    if not label_pin_present:
        return CorrectionLocationEvaluation(
            "NO_LABEL_PIN", (), refs, semantic
        )
    if not sources:
        return CorrectionLocationEvaluation(
            "NO_ELIGIBLE_H4_LABEL_GROUP", (), refs, semantic
        )
    if len(sources) != 1:
        return CorrectionLocationEvaluation(
            "AMBIGUOUS_H4_LABEL_GROUPS", (), refs, semantic
        )

    source = sources[0]
    if source["kind"] == "ABSTENTION":
        return CorrectionLocationEvaluation(
            "H4_LABEL_ABSTENTION", (), refs, semantic
        )

    primary = source["primary"]
    if primary is None:
        return CorrectionLocationEvaluation(
            "H4_PRIMARY_INTERPRETATION_MISSING", (), refs, semantic
        )
    depth = primary["correction_depth_ppm"]
    if depth is None:
        return CorrectionLocationEvaluation(
            "H4_CORRECTION_DEPTH_UNAVAILABLE", (), refs, semantic
        )

    return CorrectionLocationEvaluation(
        "H4_CORRECTION_DEPTH_MEASURED",
        ({"name": "correction_depth_ppm", "value": depth, "unit": "ppm"},),
        refs,
        semantic,
    )
