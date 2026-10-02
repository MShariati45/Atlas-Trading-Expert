# Atlas v2 P0-6 — Candidate-First Capture

Owner: Ali Shariati
Status: implementation scope

P0-6 implements the immutable candidate-ledger boundary. It captures every raw M15 setup before any H4/H1/Fib/news/session/risk/cost evaluation is allowed to act on it.

## Separation rule

Detector/capture code may use the frozen dataset and causal market inputs. It must not read news, portfolio risk, P&L, outcomes, execution state, or downstream evaluation results. Those belong to P0-7+.

## Invocation and receipt

- DetectorInvocation pins run attempt, dataset, detector ID/version, instrument, M15 timeframe, as-of time, and canonical detector parameters.
- Invocation identity is deterministic and contains no wall-clock metadata.
- RawDetectionReceipt is durable before Candidate normalization.
- occurrence_key deliberately excludes detector version and prices.
- occurrence_key binds instrument, timeframe, pattern family, direction, trigger time, and sorted causal anchors containing only role + time.
- trigger_time <= detected_at <= available_at <= invocation as_of.
- evidence references are sorted, unique Atlas market-fact IDs.
- raw payload is canonical ACE-1 JSON; floats are forbidden.

## Candidate

- At most one immutable Candidate exists per raw receipt.
- Candidate copies the receipt occurrence identity, market identity, detector identity, evidence references, timing, and taint.
- Optional entry_reference_price and structural_invalidation_price are integer references only. P0-6 does not decide market/limit/stop execution semantics.
- Features are canonical ACE-1 JSON; optional confidence is integer ppm.
- Candidate identity binds the raw receipt and normalized payload. occurrence_key remains the cross-version/cross-run grouping key.

## Terminal semantics

DetectorInvocationEnd is immutable with COMPLETED/FAILED/ABORTED status and actual receipt/candidate counts. Once terminal, no new receipt or candidate can be added. COMPLETED is legal only when every raw receipt has exactly one Candidate.

## Upgradeability

P0-7 consumes immutable Candidate IDs/occurrence keys through new evaluation tables. Strategy/gate revisions never rewrite P0-6 history. New pattern families or detector versions create new versioned invocations and can share an occurrence_key when the same causal market occurrence is identified.

## Scope exclusions

No H4/H1/Fib evaluation, news/session/spread gates, strategy ranking, outcome resolution, backtest scoring, broker connection, execution, UI, AI provider, or paid service is introduced in P0-6.
