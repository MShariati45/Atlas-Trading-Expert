# Atlas v2 P0-5 — Labels Closure

Owner: Ali Shariati  
Status: CLOSED — implementation and integration review complete

## Implemented

- Causal LabelTaskSeed and LabelTask evidence with deterministic blind transforms.
- IDENTITY_PRICE transform derives only from HMAC(study_secret, seed_id); the study secret is never persisted.
- Historical label-task creation passes through the P0-3 LABEL_TASK holdout guard before a task is returned.
- Holdout request identity includes the full seed identity, preventing collisions when study parameters differ.
- Atomic LabelSubmissionGroup writes with task-scoped request-key idempotency.
- OPERATIONAL, RETROSPECTIVE, LEGACY_IMPORT, and ENGINE modes remain distinct.
- OPERATIONAL availability equals the server submission time; non-operational groups never acquire an operational availability timestamp.
- RETROSPECTIVE and LEGACY_IMPORT taints are enforced, and inferred-reconstruction anchors require matching taint.
- Revisions are append-only and must supersede the current prior statement for that task + labeler.
- Interpretation ranks, probability totals, correction metadata, anchor time causality, and complete-bar cutoffs are validated.
- Submission groups are sealed atomically with interpretations and anchors.
- OperationalLabelView excludes retrospective/legacy/engine labels and respects as-of time.
- ResearchLabelView preserves all modes and taints.
- Selection takes the latest eligible statement per authorized labeler; abstentions are not skipped.
- Versioned selector policies support per-labeler latest and latest-authorized-owner behavior.
- Immutable LabelSetPin evidence freezes selected group IDs for downstream P0-6/P0-7 consumers.
- Deterministic direction agreement, Cohen kappa, abstention rate, and anchor-within-k-bars metrics are included.
- Raw SQL guards enforce task cutoff consistency, revision lineage, inferred-anchor taint, anchor causality, group completeness, immutability, and seal integrity.

## Upgradeability

ADR-007 is now binding for Atlas v2. P0-6 consumes P0-5 through immutable LabelSetPin/group contracts; it must not rewrite label evidence or selection history. Future labeling policies arrive as new selector/contract versions or additive migrations.

## Validation

- Python 3.14: **105/105 tests PASS**.
- Python 3.12: **105/105 tests PASS**.
- git diff --check: PASS.
- python3 -m compileall -q atlas2: PASS.
- All prior P0-1 through P0-4 tests remain green.

## Review note

Local Codex and Claude independent-review invocations were attempted but both were blocked by their local usage/session limits. Per the owner instruction that tooling quotas must not stop implementation, the integration room performed the P0-5 contract/code review directly, found and fixed two request-identity hazards plus raw causal-schema gaps, and reran the complete dual-runtime suite before closure. A later external read-only audit may review this immutable checkpoint without changing its evidence history.

## Scope preserved

No candidate detector, strategy gate, outcome simulator, broker connection, execution path, UI, paid service, or external API was introduced in P0-5.
