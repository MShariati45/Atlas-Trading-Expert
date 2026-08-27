# Technical Handoff — Atlas v0.24.31

## Scope
Authenticated UI integration on top of the hardened v0.24.30 security boundary. This is still DEMO/STAGING software.

## Runtime boundaries
Public landing page -> authenticated web/API -> read-model/application services -> persisted Atlas state.

The web/API code does **not** import MT5 order transports or execution gates. Order mutation remains exclusively in the controlled DEMO entry and supervised DEMO management layers introduced in v0.24.28-v0.24.29.

## Key files
- `run_secure_staging_web.py`
- `atlas/api/app_service.py`
- `atlas/api/read_models.py`
- `atlas/security/auth_store.py`
- `web/public/app/login.html`
- `web/public/app/index.html`
- `web/public/app/app.css`
- `web/public/app/app.js`
- `tests/test_v02431_authenticated_ui_integration.py`

## External-review focus
1. Authorization bypass by manually calling API routes.
2. Trader cross-account data leakage.
3. CSRF/session handling and secure-cookie deployment assumptions.
4. XSS risk from persisted lead/user/runtime values rendered in the client.
5. Public/private route separation.
6. Read-model leakage of broker credentials/secrets.
7. Concurrency between runtime-state writers and the UI readers.
8. Whether a browser/API request can reach any MT5 mutation path indirectly.

## Known deployment limitation
`run_secure_staging_web.py` is intentionally a loopback-only staging server. Do not expose it directly to the public internet. Production/domain staging should terminate TLS at a hardened reverse proxy/application server and use `ATLAS_COOKIE_SECURE=1`.
