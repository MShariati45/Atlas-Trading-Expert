# Atlas v2 ATX00-1 — Replay / Accounting Fidelity Scope

Owner: Ali Shariati
Status: CLOSED — fidelity-primitives slice implemented, reviewed, and validated
Research alias: ATX-00
Authority: LAB ONLY / NO ORDER

## Source basis

This slice implements only source-backed invariants from the archived 2026-10-02 research pack:
- no favorable same-bar TP/SL ordering without path evidence;
- gap-through-stop must not be priced at the stale stop;
- requested stop changes are not active before acknowledgement;
- rejected stop changes do not alter protection;
- partial fills use actual filled volume;
- explicit costs are charged once;
- account-currency conversion must be explicit;
- daily/account windows use declared boundaries rather than hidden timezone assumptions;
- pending/open risk can coexist and must be counted concurrently;
- cash/trade logs must reconcile;
- historical event time does not make a feature causal before availability/confirmation.

## Included

- Pure deterministic OHLC barrier-resolution primitive for manually specified golden cases.
- Explicit executable price basis: LONG exits require BID OHLC; SHORT exits require ASK OHLC.
- Same-bar stop/target ambiguity.
- Gap-through-stop resolution using the scenario's first executable bar price.
- Stop request / acknowledgement / rejection timing.
- FIFO fill reconciliation with explicit account-currency cash factor.
- Fill chronology forbids exits before sufficient entry volume exists.
- Fail-closed handling when same-time entry/exit fills or stop updates lack source sequence.
- Fill cost fields use positive-cost semantics; raw broker signs require an adapter.
- Explicit half-open risk window primitive.
- Concurrent risk commitment snapshot.
- Account balance reconciliation.
- Feature event/availability/confirmation causality check.
- ATX-00 preregistration payload mapped to the existing Atlas ResearchRegistry.
- Deterministic self-check packet.

## Explicit exclusions

- No production OutcomeAttachment resolver.
- No broker/MT5 adapter.
- No assumption that M15 OHLC proves intrabar order.
- No hidden spread/commission/swap/slippage defaults.
- No owner strategy parameter change.
- No actual ATX-00 confirmatory run.
- No Demo/Live/order authority.

## Accounting semantics and adapter boundary

- `net_cash_micro` is a cash-accounting quantity: realized gross on closed volume minus all fill costs already incurred, including entry costs on volume that may remain open. It is not a closed-leg-only cost allocation.
- `cash_per_price_unit_micro` is an explicit fixed factor for each golden case. A real-data adapter must supply historically correct account-currency conversion at the applicable time; this slice does not infer or cache FX conversion.
- `source_seq` is used to resolve otherwise ambiguous equal timestamps. A future raw broker adapter must also validate that broker sequence and timestamps are mutually consistent across the event stream.
- Broker-native commission/swap signs are not accepted raw by this primitive; adapters must normalize them into non-negative cost fields.

## Remaining ATX-00 work

ATX00-1 is a fidelity-primitives slice, not ATX-00 closure.

Remaining integration work:
1. bind versioned real quote/fill evidence;
2. bind historical clock/profile mapping;
3. bind real management request/ack/reject evidence;
4. replay complete chronological account state and capacity;
5. reconcile results against actual Atlas/broker logs;
6. register the final experiment with complete account, dataset, cost, window and owner-governance fields before any confirmatory claim.

Dependent ML/management experiments remain blocked from confirmatory status until those prerequisites are satisfied.
