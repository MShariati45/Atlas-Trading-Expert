# v0.24.29 Trade Management Handoff

## Safety invariant
Existing-position mutations have one legal path:

`Management policy -> SupervisedDemoManagementGate -> SQLite management claim -> DemoOnlyTradeManagementTransport -> MT5 -> broker-state verification -> audit`

The transport rechecks MT5 `ACCOUNT_TRADE_MODE_DEMO` and expected login immediately before mutation. A position must map to the original Atlas execution ledger row by account + broker position id + signal id.

## Allowed actions
1. Move stop to breakeven only after >= +1.4R.
2. Full Friday close only on Friday.
3. Protective/news full close only with explicit authorization input.
4. Owner emergency full close only with explicit Owner authorization input.

No partial close, scale-in/out, trailing stop, or arbitrary stop editing is implemented.

## Idempotency
A unique key uses account + broker position + management class. Breakeven can occur once. A full close can occur once. Uncertain broker outcomes enter reconciliation; Atlas does not retry automatically.
