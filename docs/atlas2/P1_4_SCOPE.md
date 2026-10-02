# Atlas v2 P1-4 — Correction Location Measurement

Owner: Ali Shariati
Status: CLOSED — implemented, reviewed, and validated

## Goal

Replace the placeholder CORRECTION_LOCATION evidence with a deterministic H4 correction-depth measurement from the pinned label evidence, without turning Fibonacci/correction location into an entry gate.

## Included

- Read only the EvaluationContext's immutable LabelSetPin.
- Accept only sealed H4 label groups for the same dataset/instrument and cutoff no later than the decision time.
- Measure rank-1 correction_depth_ppm when exactly one eligible pinned H4 source exists.
- Preserve CORRECTION_LOCATION as INFORMATIONAL and GateResult outcome NOT_APPLICABLE.
- Fail closed on no pin, no eligible H4 group, multiple H4 groups, abstention, missing rank-1 interpretation, or missing correction depth.
- Include pinned label-group refs and semantic source projection in evaluation evidence for replay identity.

## Excluded

- No Fibonacci entry trigger.
- No automatic aggregation of multiple labelers.
- No H4_CONTEXT pass/fail semantics.
- No M15 trigger classifier.
- No outcome resolver, portfolio sizing, broker, Demo, or Live authority.
