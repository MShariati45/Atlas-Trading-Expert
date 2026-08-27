# Atlas v0.24.33 Dashboard Activation

Purpose: activate the authenticated Owner dashboard against persisted/read-only Atlas runtime state and the MT5 DEMO terminal without adding any direct web/API order path.

## Safety boundary

- REAL MONEY remains disabled.
- `run_dashboard_activation.py` imports read-only MT5 market data only; it imports no order transport.
- A connected account is accepted only when `AccountIdentityVerifier` positively verifies MT5 `trade_mode == DEMO`, the server name looks DEMO, trading is allowed, and Expert trading is allowed.
- If DEMO verification fails, the dashboard publishes a fail-closed WAITING/UNAVAILABLE snapshot and execution remains locked.
- Existing ControlledDemoExecutionGate / DemoOnlyMT5Transport and supervised management boundaries are unchanged.

## What becomes functional

- Dashboard: connected DEMO account, balance/equity, terminal state, watchlist count, open positions, risk policy and live symbol health.
- Watchlist: XAUUSD, EURUSD, USDCAD, USDJPY with H4/H1 state, prices/spread, calendar state, M15 coordination and Supervisor status.
- Accounts: connected DEMO snapshot, identity verification state, balance/equity/margin, open positions and execution-ledger history.
- Leads: unchanged existing lead store.
- Users & Access: current identities and Trader creation/assignment path. ADMIN creation is intentionally not exposed until a proper MFA-enrollment workflow is added.
- Security: existing authentication/security event log.
- Settings: read-only safety, risk and connection state.

## First activation on the VPS

1. Keep the existing authenticated web service and Caddy running.
2. Make sure the MT5 terminal on the VPS is open and logged into the intended DEMO account.
3. From an Administrator Command Prompt in the Atlas project folder, run:

   `start_dashboard_activation.bat`

4. The runner writes `runtime/dashboard_state.json` atomically every 15 seconds.
5. Refresh `https://app.atlastradingexpert.com` and verify:
   - DEMO VERIFIED
   - correct MT5 login/server
   - four watchlist symbols
   - current balance/equity
   - Execution = LOCKED

If the default MT5 terminal cannot be discovered, optional environment variables are supported:

- `ATLAS_MT5_ACCOUNT_ID` (safe alias, default `ATLAS-DEMO`)
- `ATLAS_MT5_TERMINAL_PATH`
- `ATLAS_MT5_LOGIN`
- `ATLAS_MT5_SERVER`
- `ATLAS_MT5_PASSWORD_ENV` (name of a password environment variable; default `ATLAS_MT5_PASSWORD`)

Do not place an MT5 password in source files or browser-visible configuration.

## Before supervised demo execution

Do not unlock any execution path merely because the dashboard is populated. Confirm the DEMO account identity, broker-native symbol mapping, live prices, H4/H1 state and watchlist freshness first. Execution remains a separate controlled activation step.
