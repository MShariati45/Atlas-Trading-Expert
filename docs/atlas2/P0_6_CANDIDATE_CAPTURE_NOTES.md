# Atlas v2 P0-6 — Candidate-First Capture Closure

Owner: Ali Shariati  
Status: CLOSED — implementation, CodeRabbit review, and dual-runtime validation complete

## Implemented

- Immutable DetectorInvocation evidence pinned to run attempt, frozen dataset, detector ID/version, M15 instrument, as-of time, and canonical parameters.
- Immutable RawDetectionReceipt committed before Candidate normalization.
- occurrence_key is deterministic and excludes detector version and prices; it binds instrument, M15 timeframe, pattern family, direction, trigger time, and sorted causal anchors.
- Raw receipt timing enforces trigger_time <= detected_at <= available_at <= invocation as_of.
- Occurrence anchors cannot be after detection time.
- Evidence references must be Atlas market fact IDs, belong to the invocation dataset, and be causally available by the receipt availability time.
- FORWARD evidence visibility respects actual source-observation acquisition time.
- Raw detection identity is content-derived and request-key retry safe.
- Candidate normalization is one-to-one with raw receipts and never mutates or deletes failed raw detections.
- Candidate fields copy the raw occurrence, market identity, detector identity, evidence references, timing, and taint.
- Entry/invalidation values are integer references only; P0-6 does not define execution order semantics.
- DetectorInvocationEnd is immutable; terminal invocations reject new receipts/candidates.
- COMPLETED requires one Candidate per RawDetectionReceipt.
- Raw SQL guards protect invocation identity/as-of consistency, candidate/receipt matching, terminal state, counts, and immutability.
- Downstream evaluation, outcomes, broker execution, news/risk/P&L, and legacy execution authority remain outside the P0-6 module.

## CodeRabbit review

Two review passes were run against the uncommitted P0-6 change set with the Atlas-specific review policy. CodeRabbit reported only minor issues; all valid findings were fixed before closure:

- reject string/bytes evidence-ref inputs explicitly;
- harden the raw-SQL invocation/as-of trigger against missing or mismatched invocation identity;
- bind receipt instrument/timeframe/detector ID/version to the invocation at the schema boundary.

No CodeRabbit blocker was reported.

## Validation

- Python 3.14: **121/121 tests PASS**.
- Python 3.12: **121/121 tests PASS**.
- Focused Candidate Capture tests: **16/16 PASS**.
- `git diff --check`: PASS.
- `python3 -m compileall -q atlas2`: PASS.
- All P0-1 through P0-5 tests remain green.

## Upgradeability

P0-7 must consume immutable Candidate IDs and occurrence keys through additive evaluation/replay tables. No strategy/gate revision is allowed to rewrite P0-6 receipts or candidates. Detector evolution occurs by adding detector versions and new invocations.

## Scope preserved

No strategy evaluation, outcome simulation, broker connection, execution path, UI, AI provider, or paid service was introduced in P0-6.
