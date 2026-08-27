# Atlas v0.24.30 Technical Handoff - Secure Private-App API/Auth

## Purpose
Add an authenticated private-application boundary without exposing MT5 mutation capability to the browser/API layer.

## New components
- `atlas/security/auth_store.py`: transactional SQLite users, assignments, sessions, CSRF hashes, MFA secrets, security events.
- `atlas/security/rate_limit.py`: local staging rate limiter.
- `atlas/api/app_service.py`: role-enforced application service with no execution imports.
- `run_secure_staging_web.py`: loopback-only staging HTTP/API adapter with security headers, sessions, CSRF and lead/login endpoints.
- `bootstrap_owner.py`: one-time empty-database Owner bootstrap with mandatory TOTP secret.

## Invariants
1. Public lead submission never grants Atlas access.
2. Only Owner can create users or assign accounts.
3. Trader access is read-only and limited to assigned account IDs.
4. Owner/Admin MFA is required by default at account creation.
5. Session tokens are stored only as hashes.
6. Authenticated mutations require CSRF validation.
7. Suspension revokes active sessions.
8. The private web/API boundary has no MT5/order-send imports or endpoints.
9. The staging server refuses non-loopback binding. Internet exposure must terminate TLS in a reverse proxy/application gateway.
10. Real-money execution remains disabled/out of scope.

## Validation
- `compileall`: PASS
- `pytest`: 303/303 PASS
- Dedicated tests cover MFA login, session+CSRF validation, logout/revocation, owner-only user creation, multi-account assignment, Trader read-only behavior, suspension, bootstrap uniqueness and concurrent username creation.

## Known next-stage work
- Wire approved visual login/private UI to these endpoints.
- Add password-reset/recovery workflow without revealing account existence.
- Add production-grade distributed rate limiting at the proxy/gateway.
- Add cloud secret manager / key encryption for MFA and MT5 credentials.
- Add real account financial-data read adapters behind AccessPolicy.
- Add owner/admin audit UI and approximate-login-region enrichment if desired.
- Deploy behind TLS, configure DNS, CSP asset policy and secure headers at reverse proxy.
- Market-open broker calibration and integrated DEMO validation remain separate gates.
