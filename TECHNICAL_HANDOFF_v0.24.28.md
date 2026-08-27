# Atlas v0.24.28 - Technical Handoff After Independent Reviews

This package supersedes v0.24.27 for further engineering review. It incorporates the confirmed findings from the Grok and Claude reviews rather than merely documenting them.

## Review these invariants first

1. `atlas/execution/demo_runtime.py` is the canonical DEMO execution integration seam.
2. There must be exactly one new-order `mt5.order_send` path: `atlas/execution/demo_transport.py`.
3. `ControlledDemoExecutionGate` must use the same `SQLiteExecutionLedger` as the transport and authoritative risk-state service.
4. Daily limits must be derived from ledger + live MT5 positions, never caller-supplied zero defaults.
5. Scheduled-news provider unavailable/stale must block a new entry.
6. H4 human approval must expire/review rather than live forever.
7. Any uncertain broker send must remain a consumed/blocked execution claim until reconciliation.
8. LIVE/REAL MT5 trade mode must be impossible to pass at account enablement and pre-send transport verification.
9. Legacy bridge new-order, modify-stop, and close-position mutation methods must not send orders.

## Known intentional limitation

Automated stop modification and early close are disabled in this checkpoint. Initial broker-side SL/TP still protect an opened DEMO position. A dedicated supervised trade-management boundary must be added and tested before breakeven-stop automation is enabled.

## Verification at packaging time

- pytest: 289 passed
- compileall: PASS
- demo transport offline self-check: PASS
- only one `order_send(` occurrence under `atlas/`, in `demo_transport.py`
- no real broker orders sent during package construction
