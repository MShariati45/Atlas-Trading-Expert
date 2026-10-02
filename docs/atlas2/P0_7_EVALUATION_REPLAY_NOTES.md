# Atlas v2 P0-7 — Evaluation + Replay Closure

Owner: Ali Shariati  
Status: CLOSED — implementation, CodeRabbit review, and dual-runtime validation complete

## Implemented

- MarketSnapshot evidence pins dataset, instrument, as-of time, PIT/NON_PIT view class, REPLAY/FORWARD visibility mode, canonical windows, visible-fact digest, and taint.
- CaptureUnit seals the semantic detector/candidate peer set independently of run-attempt IDs.
- Capture sealing requires snapshot membership, invocation/end pairing, complete inclusion of existing receipts/candidates, and candidate membership consistent with the frozen dataset/instrument/decision time.
- EvaluationContext pins the sealed capture unit, label pin, macro view class, mode, and derived taint. Evaluation mode must match snapshot visibility mode.
- CandidateRelation is directed and versioned for SAME_EVENT_DUPLICATE, CONFIRMS, and PRIMARY_OF.
- GateResult supports the frozen gate vocabulary, typed/sorted input refs, integer measurements, explicit errors, and measurement-only CORRECTION_LOCATION semantics.
- StrategyVersion and ArmResult are immutable/versioned; one plan per strategy version.
- C0 minimal control evaluates DATA_QUALITY only. PASS accepts, FAIL rejects, ERROR errors, and WAIT/ABSTAIN/NOT_EVALUABLE abstain.
- C0 evaluates every candidate in the sealed peer set and records exactly one ArmResult per candidate/context/strategy version.
- Evidence that is not causally visible in the requested mode becomes DATA_QUALITY NOT_EVALUABLE / EVIDENCE_NOT_VISIBLE rather than aborting the context.
- Evaluation faults roll back the evaluation transaction without deleting capture receipts/candidates; retry resumes deterministically.
- OutcomeAttachment contract and fixture-only OutcomeBatch persistence are present. Fixtures are SYNTHETIC_DATA tainted and inherit subject taint. The production resolver remains P1.
- Replay digests use only explicitly confirmed sealed CAPTURE_UNIT / EVALUATION_UNIT / OUTCOME_BATCH aggregates and exclude attempt/request/audit timing noise.
- Fresh-store replay, crash/resume replay, reused-store retry, label-pin change, cross-dataset semantic-prefix behavior, immutability, and raw-SQL seal invariants are covered.

## Review fixes applied

Earlier CodeRabbit review passes identified and the integration room fixed:
- fixture outcome taint did not initially inherit subject taint;
- sealed evaluation retry ordering differed from first-run occurrence ordering;
- sealed outcome-batch retry compared semantic digests but not outcome IDs;
- architecture import guard missed some relative/root store imports;
- invisible evidence raised instead of producing NOT_EVALUABLE;
- snapshot visibility mode was not originally pinned into snapshot identity;
- capture sealing needed stronger receipt/invocation/candidate completeness links.

All fixes have regression tests.

## Validation

- Python 3.14: **149/149 tests PASS**.
- Python 3.12: **149/149 tests PASS**.
- Focused P0-7 evaluation/replay tests: **27/27 PASS**.
- `python3 -m compileall -q atlas2`: PASS.
- `git diff --check`: PASS.
- All P0-1 through P0-6 tests remain green.

## Upgradeability

P1 consumes immutable Candidate, CaptureUnit, EvaluationContext, GateResult, ArmResult, OutcomeAttachment, and replay contracts. Owner Track A/C0/optional Track B, the production outcome resolver, portfolio scenarios, and forward Shadow runtime arrive as versioned/additive components. P0-7 history is not rewritten.

## Scope preserved

No production owner strategy semantics, real outcome resolver, portfolio sizing, broker SDK, execution, live risk governor, UI, hosted AI provider, or paid runtime service was introduced in P0-7.
