# Atlas v0.24.28 - Independent Review Remediation

This checkpoint remediates the critical/high-confidence findings from two independent AI code reviews of v0.24.27. It remains DEMO/STAGING only; REAL/LIVE order execution is out of scope.

## Accepted findings fixed

- Unified execution idempotency on one transactional SQLite ledger. The JSON execution ledger is removed from the runtime execution path.
- Removed check-then-claim TOCTOU from the final gate. Atomic SQLite claim decides the winner; concurrent duplicates are returned as a clean blocked decision.
- Added canonical `DemoExecutionRuntime` that shares one ledger across risk-state, gate, and transport.
- Daily trade count, per-symbol count, committed daily risk, and open-symbol position state are now derived by `MT5AccountRiskStateService`; callers no longer pass zero-default counters to the gate.
- Final execution gate now requires `LiveNewsGuardService`; unavailable/stale provider data fails closed rather than being interpreted as clear news.
- H4 human approvals now expire (24h default) and optionally carry a structure token that forces re-review on structure change.
- Account execution enablement now records authoritative MT5 DEMO identity; transport still re-verifies trade mode immediately before send.
- Legacy `modify_stop` and `close_position` MT5 bridge mutations are disabled until they are routed through a dedicated supervised management boundary.
- Broker send durability improved with durable `SEND_ATTEMPTED` before `order_send`, immediate `SEND_ACKED` after broker acceptance, and restart reconciliation support. Uncertain sends consume risk until reconciled.
- Broker-native risk sizing can use MT5 `order_calc_profit` through `MT5BrokerContractService`, avoiding the assumption that every symbol/account uses identical tick economics.
- Audit log is hash-chained, redacts common secret keys, flushes and fsyncs critical records.
- Package metadata/version labels updated to 0.24.28.

## Verification

- `pytest`: 288 passed
- `python -m compileall`: PASS
- No LIVE/REAL execution path enabled.

## Intentionally still pending

- Dedicated supervised trade-management transport for breakeven stop moves/manual risk-reducing closes. Legacy direct mutations are intentionally blocked until this exists.
- Production authentication/MFA/session stack, cloud secrets vault, TLS/reverse proxy deployment.
- Market-open broker calibration and end-to-end Windows/MT5 demo validation.
- Full reporting/analytics completion.
