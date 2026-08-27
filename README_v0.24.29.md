# Atlas v0.24.29 - Supervised DEMO Trade Management

This checkpoint restores only the first approved management actions for already-open Atlas DEMO positions behind a new safety boundary.

## Added
- `SupervisedDemoManagementGate` and `DemoOnlyTradeManagementTransport`.
- Broker-side DEMO identity is re-verified immediately before every management mutation.
- Position ownership is proven against the transactional execution ledger before mutation.
- Atomic management-action idempotency using the same SQLite execution database.
- Breakeven move allowed only at/after +1.4R and never allowed to loosen an existing stop.
- Full close actions limited to Friday mandatory close, explicitly-authorized protective/news close, and explicitly-authorized Owner emergency close.
- `SEND_ATTEMPTED`, `SEND_ACKED`, verification and reconciliation states for management mutations.
- Restart reconciliation for uncertain stop/close actions; never automatically retries.
- Hash-chained durable audit records are reused for management actions.

## Still intentionally disabled
- partial closes / scaling;
- trailing-stop experiments;
- arbitrary manual stop changes from Trader/Admin UI;
- management on LIVE/REAL accounts;
- any new-order path outside the controlled DEMO execution transport.

The old `MT5PythonBridge.modify_stop()` / `close_position()` methods remain disabled.
