# Atlas Trading Expert v0.24.27 - Technical Architecture Hardening / AI Handoff

Purpose: harden the v0.24.26 demo transport architecture before secure web/API deployment and provide a self-contained package for independent technical review.

## Changes in v0.24.27

1. Transactional SQLite operational state
   - Added `atlas/core/sqlite_state_store.py`.
   - WAL mode, busy timeout, atomic writes, and atomic read-modify-write via `update()`.
   - Live H4/H1 observation runtime now uses SQLite rather than shared JSON state.
   - Runtime defaults changed from `.json` structure state to `.sqlite3`.

2. Transactional execution idempotency
   - Added `atlas/execution/sqlite_execution_ledger.py`.
   - `(account_id, signal_id)` is a database primary key, preventing duplicate claims across processes.
   - `DemoOnlyMT5Transport` now defaults to the SQLite execution ledger.
   - Legacy JSON `ExecutionLedger` remains only for backward compatibility/tests and should not be chosen for deployed multi-process runtime.

3. One authoritative DEMO identity model
   - Added `atlas/execution/account_identity.py`.
   - Authorization and MT5 transport use the same identity rules.
   - MT5 `ACCOUNT_TRADE_MODE_DEMO` is authoritative at send time; server/config text is defense-in-depth only.

4. Legacy new-order path disabled
   - `MT5PythonBridge.place_order()` can no longer create new positions, even when generic execution is enabled.
   - New positions must go through `ControlledDemoExecutionGate -> DemoOnlyMT5Transport`.
   - `modify_stop()` and `close_position()` remain available for supervised trade management and are still execution-locked by default.

5. MT5 transport configuration centralized per account
   - Added `password_env`, `max_deviation_points`, `atlas_magic`, and optional filling-mode override to `MT5ConnectionSettings`.
   - Environment-secret reference is preferred over embedding an MT5 password in config.
   - Filling mode is derived from broker symbol capabilities where available, then validated with mandatory `order_check`.

6. Stronger post-fill correlation
   - Position verification prefers exact broker order/position identifiers, then deal-to-position mapping if available.
   - Symbol/magic/time correlation is only a fallback.

## Verification

- Python compileall: PASS
- Full pytest suite: **281 passed**
- New v0.24.27 tests cover SQLite atomic update, cross-instance duplicate execution claims, and legacy direct-order path rejection.
- No real broker order was sent while building/testing this package.

## Deliberately not claimed as production-ready

The following are still required before a public production application or real-money use:

- secure application API/authentication/session/MFA stack;
- secrets manager / encrypted credential lifecycle beyond env-reference support;
- production web server/reverse proxy/TLS deployment;
- final report analytics TODOs;
- fresh market-open broker spread calibration;
- live DEMO transport validation using a naturally generated Atlas signal;
- end-to-end multi-user staging tests;
- supervised trade-management boundary hardening for stop modification/close commands;
- operational monitoring/backups/database migrations.

**REAL/LIVE MONEY EXECUTION REMAINS OUT OF SCOPE AND MUST STAY DISABLED.**
