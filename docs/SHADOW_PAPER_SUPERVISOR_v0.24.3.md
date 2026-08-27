# Atlas v0.24.3 — Shadow Paper Supervisor

This checkpoint integrates the validated four-currency official scheduled-news backbone into the continuous read-only M15-first Supervisor path.

## Safety
- MT5 order transmission remains hard locked.
- The runtime never calls `order_send`.
- Missing/stale/partial news forces WAIT.
- Missing or unapproved broker-cost policy forces WAIT.
- Read-only spread calibration is evidence only and never auto-activates limits.

## Runtime flow
1. H4 and H1 agents update independently.
2. M15 specialists scan both directions.
3. Pair/pattern-specific HTF policy is applied after a mature M15 package exists.
4. Supervisor checks calendar/session, static-zone path, official scheduled news, broker-cost policy, structural stop, risk limits and freshness.
5. State is written to `runtime/atlas_shadow_supervisor_state.json`.
6. New/changed mature candidates are journaled to `runtime/atlas_shadow_supervisor_journal.jsonl`.

## News fail-safe
The JSON provider revalidates required currencies and required event families on every read. If a later refresh degrades from full coverage to partial coverage, the Supervisor immediately receives `NEWS_DATA_UNAVAILABLE` and must WAIT.

## Broker-cost fail-safe
`config/broker_cost_policy.template.json` is intentionally unapproved. Atlas requires a separate `config/broker_cost_policy.json` with `approved=true` and complete per-symbol spread/slippage limits before the market-cost gates can pass.

This stage is shadow supervision only. It is not paper fill simulation and not demo order execution.
