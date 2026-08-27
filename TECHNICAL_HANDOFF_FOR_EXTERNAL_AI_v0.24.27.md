# Independent AI / Engineer Review Handoff

## Review target
Atlas Trading Expert **v0.24.27 Technical Architecture Hardening**.

This package is a DEMO/STAGING trading platform prototype. Please review the actual source code rather than inferring behavior from README files.

## Current intended runtime chain

`market data -> agents -> coordinator -> supervisor -> H4 human approval -> news guard -> adaptive spread guard -> risk/authorization -> ControlledDemoExecutionGate -> DemoOnlyMT5Transport -> MT5 DEMO -> fill verification/audit`

The web application is not yet the production runtime and must not directly call MT5 mutation methods.

## Security/safety invariants to challenge

1. A LIVE/REAL MT5 account must never pass the DEMO transport.
2. New orders must have one legal path only: ControlledDemoExecutionGate -> DemoOnlyMT5Transport.
3. Duplicate `(account_id, signal_id)` sends must be impossible across processes/restarts.
4. 0.5% per-trade risk, 1% daily cap, two trades/day, one open position/symbol and 2R baseline must fail closed.
5. Missing/stale news, unavailable spread baseline, abnormal spread, stale market data, invalid H4 approval, or invalid broker contract must block new execution.
6. No LLM/API availability should be required for risk protection or order management.
7. A Trader user must never gain Owner/Admin capabilities through client-side UI manipulation.
8. MT5 credentials/secrets must never be exposed to browser clients or logs.

## Areas where an adversarial review is specifically requested

- SQLite transaction semantics and idempotency under concurrent processes.
- Any remaining alternate path to `order_send` that could open a new position.
- Race conditions between authorization, spread/news state, and actual send.
- TOCTOU between ticket preparation and MT5 execution.
- Lot/risk math across FX, JPY pairs, metals, broker tick-value differences, account currency differences.
- Filling mode / execution-mode compatibility across MT5 brokers.
- Position/deal/order correlation after partial fills, netting accounts, hedging accounts, requotes, and rejected orders.
- Restart/recovery behavior after `order_send` succeeds but local persistence fails.
- Durability and integrity of audit logs.
- Credential lifecycle and future API/session authorization boundaries.
- Whether H4 approval state can become stale while remaining nominally approved.
- Test gaps: integration, property-based, concurrency, fault injection, and Windows/MT5-specific cases.

## Known remaining limitations (not bugs hidden from reviewer)

- `run_staging_web.py` is a staging server, not production hosting.
- Full authentication/MFA/session implementation is not complete yet.
- `MT5PythonBridge.modify_stop()` and `close_position()` remain mutation-capable when execution is enabled; they are intended for supervised trade management but need the same formal application-service boundary before public deployment.
- Environment-referenced secrets are supported, but a cloud secrets vault is not implemented yet.
- Advanced performance reporting remains incomplete.
- Market-open calibration and real DEMO fill/slippage evidence are still pending.
- Real-money execution is intentionally not supported/approved.

## Automated status

`python -m compileall -q atlas` -> PASS

`python -m pytest -q` -> **281 passed**

## Requested reviewer output

Please return findings grouped as:

- CRITICAL - could cause unauthorized/live execution, duplicate trades, wrong risk, secret exposure, or corrupt account isolation.
- HIGH - could cause incorrect demo execution, lost state, incorrect fills/reporting, or unsafe recovery.
- MEDIUM - architecture/performance/maintainability issue worth fixing before scale-up.
- LOW - code quality/documentation/test improvement.

For each finding include exact file/function, failure scenario, why current tests may miss it, and a minimal recommended correction. Please distinguish confirmed defects from theoretical risks.
