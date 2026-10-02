"""Pure P1 H4 owner-context direction policy.

Track A requires the M15 candidate direction to align with the owner-authorized
H4 impulse direction. RANGE/TRANSITION and unavailable evidence remain
NOT_EVALUABLE rather than being guessed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class H4ContextEvaluation:
    outcome: str
    reason_code: str
    measurements: tuple[dict, ...]
    label_group_refs: tuple[str, ...]
    source_semantic: tuple[dict, ...]


def evaluate_h4_context(
    sources: tuple[dict, ...],
    *,
    label_pin_present: bool,
    pin_view_kind: str | None,
    selector_policy_version: str | None,
    authorized_owner_labelers: tuple[str, ...],
    candidate_direction: str,
) -> H4ContextEvaluation:
    """Evaluate owner-authorized H4 direction without inventing structure."""
    refs = tuple(sorted(source["group_id"] for source in sources))
    ordered = tuple(sorted(sources, key=lambda item: item["group_id"]))
    semantic = tuple(source["semantic"] for source in ordered)

    if candidate_direction not in {"LONG", "SHORT"}:
        raise ValueError("candidate_direction must be LONG/SHORT")
    if not authorized_owner_labelers:
        raise ValueError("authorized_owner_labelers cannot be empty")
    if not label_pin_present:
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "NO_LABEL_PIN", (), refs, semantic
        )
    if pin_view_kind != "OPERATIONAL":
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "H4_OWNER_OPERATIONAL_PIN_REQUIRED", (), refs, semantic
        )
    if selector_policy_version != "latest-authorized-owner-v1":
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "H4_OWNER_SELECTOR_REQUIRED", (), refs, semantic
        )
    if not sources:
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "NO_ELIGIBLE_H4_LABEL_GROUP", (), refs, semantic
        )
    allowed = set(authorized_owner_labelers)
    if any(source["labeler_id"] not in allowed for source in sources):
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "H4_OWNER_LABELER_REQUIRED", (), refs, semantic
        )
    if any(not source["is_sealed"] for source in sources):
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "H4_LABEL_GROUP_UNSEALED", (), refs, semantic
        )
    if any(not source["is_causal"] for source in sources):
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "PINNED_H4_GROUP_NOT_CAUSAL", (), refs, semantic
        )
    if len(sources) != 1:
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "AMBIGUOUS_H4_LABEL_GROUPS", (), refs, semantic
        )

    source = sources[0]
    if source["kind"] == "ABSTENTION":
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "H4_LABEL_ABSTENTION", (), refs, semantic
        )
    primary = source["primary"]
    if primary is None:
        return H4ContextEvaluation(
            "NOT_EVALUABLE", "H4_PRIMARY_INTERPRETATION_MISSING", (), refs, semantic
        )

    trend = primary["trend"]
    if trend == "RANGE":
        return H4ContextEvaluation(
            "NOT_EVALUABLE",
            "H4_OWNER_DIRECTION_RANGE",
            ({"name": "owner_h4_confidence", "value": primary["confidence"], "unit": "score_1_5"},),
            refs,
            semantic,
        )
    if trend == "TRANSITION":
        return H4ContextEvaluation(
            "NOT_EVALUABLE",
            "H4_OWNER_DIRECTION_TRANSITION",
            ({"name": "owner_h4_confidence", "value": primary["confidence"], "unit": "score_1_5"},),
            refs,
            semantic,
        )

    aligned = (
        (candidate_direction == "LONG" and trend == "BULLISH")
        or (candidate_direction == "SHORT" and trend == "BEARISH")
    )
    measurements = [
        {"name": "owner_h4_confidence", "value": primary["confidence"], "unit": "score_1_5"}
    ]
    if primary["probability_ppm"] is not None:
        measurements.append(
            {
                "name": "owner_h4_probability_ppm",
                "value": primary["probability_ppm"],
                "unit": "ppm",
            }
        )
    measurements = tuple(measurements)
    if aligned:
        return H4ContextEvaluation(
            "PASS", "H4_OWNER_DIRECTION_ALIGNED", measurements, refs, semantic
        )
    return H4ContextEvaluation(
        "FAIL", "H4_OWNER_DIRECTION_CONFLICT", measurements, refs, semantic
    )
