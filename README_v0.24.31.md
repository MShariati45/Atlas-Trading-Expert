# Atlas Trading Expert v0.24.31 — Authenticated UI Integration

This checkpoint connects the approved Atlas visual shell to the secure v0.24.30 application boundary and persisted Atlas read models.

## Added
- Real responsive `/app/login` screen using the approved Concept A identity.
- Authenticated `/app/` application shell; unauthenticated requests redirect to Client Login.
- Role-aware navigation for OWNER / ADMIN / TRADER.
- Owner/Admin dashboard reads persisted Atlas runtime health and symbol state.
- Watchlist reads persisted bid/ask, H4 state, M15/coordinator/supervisor state, spread, and H4 human approval state.
- Owner/Admin H4 confirmation form wired to the H4 approval store with expiry controls inherited from v0.24.28.
- Multi-account read-only Trader view and account switching/detail pages.
- Execution-history read model from the transactional SQLite execution ledger.
- Leads, Users & Access, Security Activity, and Settings views connected to authenticated endpoints.
- Owner-only user creation remains server enforced.
- Browser/API layer remains unable to import MT5 execution transports or call `order_send`.

## Safety invariants
- DEMO / STAGING only. REAL MONEY remains disabled.
- Web UI cannot directly open, modify, or close MT5 positions.
- Trader is read-only and can only view assigned accounts.
- Owner/Admin access is enforced server-side, not merely by hidden UI elements.
- Public Request Information does not create a user or grant access.
- H4 approval is a strategy-state workflow only; it is not an order endpoint.

## Validation
- Python `compileall`: PASS
- Full pytest suite: **307 / 307 PASS**
- New UI/read-model tests cover static app assets, execution-import separation, role-filtered account views, live watchlist read model, owner dashboard, and user listing.

## Remaining before domain staging
1. Run behind a real HTTPS/TLS reverse proxy and set `ATLAS_COOKIE_SECURE=1`.
2. Replace the stdlib staging HTTP server with a production WSGI/ASGI deployment boundary before public exposure.
3. Add final account-worker/live snapshot aggregation for multiple simultaneous MT5 terminal workers.
4. Perform browser/device acceptance testing on desktop and mobile.
5. Perform market-open broker calibration and fresh preflight before enabling DEMO execution.
6. Forward-test lead, login, MFA, Trader assignment, report/view isolation, H4 confirmation, entry and management workflows end-to-end.
