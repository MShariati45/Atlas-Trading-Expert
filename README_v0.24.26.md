# Atlas v0.24.26 - DEMO Transport Integration

This checkpoint connects the authorized DEMO_ONLY execution ticket to a hardened MT5 transport contract while preserving fail-closed defaults.

## New safeguards
- Positive MT5 `ACCOUNT_TRADE_MODE_DEMO` verification immediately before send.
- Optional exact-login match immediately before send.
- LIVE/REAL trade mode or server marker is categorically rejected.
- Broker symbol mapping is respected by the MT5 bridge.
- `order_check` must pass before `order_send`.
- No automatic retry after rejection/failure.
- Post-fill position lookup and verification of fill price, volume, SL and TP.
- Slippage/effective-risk evidence is logged locally.
- Append-only JSONL execution audit plus idempotency ledger status.
- No AI/API calls in transport.

## Important
Execution remains disabled by default. `MT5PythonBridge(..., execution_enabled=False)` is still the default. This package does not include an automatic live-money path. The first actual send must happen only after fresh-market broker calibration, valid news, fresh preflight, H4 owner confirmation and explicit DEMO_ONLY authorization.

Run `run_demo_transport_selfcheck.bat` offline to validate the send/fill/verify contract against a fake MT5 adapter. It sends zero broker orders.
