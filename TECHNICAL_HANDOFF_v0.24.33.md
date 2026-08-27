# Atlas v0.24.33 - Authenticated Dashboard Activation

v0.24.33 activates the previously present private-app tabs against a normalized persisted read model while preserving the v0.24.32 TLS/authentication boundary.

Changes:
- Added `run_dashboard_activation.py`, a read-only MT5 DEMO observation runtime that atomically maintains `runtime/dashboard_state.json`.
- Added authoritative DEMO identity verification before a connected MT5 account is surfaced as verified.
- Owner/Admin automatically see the locally connected read-only account snapshot even before Trader assignment; this grants no execution authority.
- Dashboard now exposes account, terminal, open-position and risk-policy state.
- Accounts page now exposes read-only broker snapshot, DEMO verification, open positions and demo execution ledger history.
- Settings page reflects live safety/risk/connection state.
- Watchlist remains the frozen four-symbol profile: EURUSD, USDJPY, USDCAD, XAUUSD.
- ADMIN creation is removed from the current web form until MFA enrollment is implemented; backend role policy remains unchanged.
- `REAL MONEY DISABLED` and execution lock remain unchanged.

Regression: 311/311 existing tests pass after the update.
