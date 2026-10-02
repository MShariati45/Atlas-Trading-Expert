# Atlas v2 P0-7 — Evaluate + Replay

Owner: Ali Shariati
Status: implementation scope

Source of truth: Atlas v2 Lean Implementation Design v2, sections 4, 5.11-5.15, 7.5, 9, and roadmap section 13.

P0-7 evaluates immutable P0-6 candidates without mutating capture history. It also provides deterministic replay evidence. Outcome resolution remains fixture/contract-only in P0; the real resolver belongs to P1.

## EvaluationContext

EvaluationContext identity pins:
- sealed capture_unit_id for dataset + instrument + decision time;
- label_pin (OPERATIONAL/RESEARCH LabelSetPin) or NULL;
- macro_view_class (PIT/NON_PIT);
- mode (REPLAY/FORWARD).

Context taint is the union of snapshot, receipt, label-view, and macro-view taints. A changed peer set, label set, selector policy, or macro view creates a new context rather than mutating an old one.

## Relations

CandidateRelation is directed and versioned. P0-7 supports the frozen relation kinds:
- SAME_EVENT_DUPLICATE
- CONFIRMS
- PRIMARY_OF

H4 disagreement is not a relation; it belongs to the H4 gate in P1.

## Gates

GateResult identity binds context, candidate, gate kind, evaluator version, and sorted typed input refs.

Outcomes:
- PASS
- FAIL
- WAIT
- ABSTAIN
- NOT_APPLICABLE
- NOT_EVALUABLE
- ERROR

Frozen gate kinds:
- DATA_QUALITY
- M15_COORDINATION
- H4_CONTEXT
- H1_CONTEXT
- CORRECTION_LOCATION
- SESSION_DAY
- NEWS_RISK
- SPREAD_COST

P0 implements only the smallest C0 path required by the architecture. C0 accepts when DATA_QUALITY passes. P1 supplies owner Track A semantics and additional active gates. CORRECTION_LOCATION is measurement-only and may not become an entry gate.

## ArmResult

ArmResult identity binds candidate, strategy_version, context, and ordered gate IDs with roles. One row exists per candidate + strategy version + context.

Decisions:
- ACCEPT
- REJECT
- ABSTAIN
- NOT_ELIGIBLE
- ERROR

ACCEPT requires every REQUIRED gate to PASS. REQUIRED ERROR => ERROR. REQUIRED WAIT/ABSTAIN/NOT_EVALUABLE => ABSTAIN.

P0 uses a versioned C0 minimal-control strategy only. The owner 2R + BE@1.4R baseline and 2R/no-BE ablation are P1 strategy versions, not P0 assumptions.

## OutcomeAttachment contract

P0 includes the immutable OutcomeAttachment contract and hand-built fixtures only. P0 does not implement the production outcome resolver. P1 adds the M15/M1 path resolver, ambiguous-path intervals, gaps, BE ordering, spread/cost handling, and proxy outcome rules.

## Replay

Replay digest is SHA-256 over sorted sealed aggregate lines for the manifest allowlist:
- CAPTURE_UNIT
- EVALUATION_UNIT
- OUTCOME_BATCH
- P1 later adds PORTFOLIO_SCENARIO

Excluded from digest: attempts, audit rows, request keys, observation acquired_at metadata, legacy aliases, holdout exposures, and timings.

Required P0-7 tests:
1. same manifest in fresh store;
2. same manifest retry in reused store writes zero new evidence rows;
3. second fresh store produces identical replay digest;
4. changed label pin creates a new EvaluationContext, not an identity conflict;
5. crash after capture but before evaluation preserves capture and resumes at evaluation;
6. candidate has exactly one C0 ArmResult in its context;
7. gate exception cannot delete receipts/candidates;
8. cross-dataset semantic-prefix fixture: facts available only after T do not change projections before T; a fact available before T does.

## Upgradeability

P1 must add Track A/C0/optional Track B strategy versions, outcome resolver, portfolio scenario, and forward runtime through new versioned evaluation components. P0-7 evaluation history is never rewritten.

## Scope exclusions

No production owner strategy rules, no real outcome resolver, no portfolio sizing, no broker SDK, no execution, no live risk governor, no UI, no paid service.
