# Atlas v0.24.30 - Secure Private-App API & Authentication

This checkpoint adds the first authenticated private-application boundary while preserving all v0.24.29 DEMO-only trading safeguards.

## Security model
- SQLite transactional user/session/security-event store.
- Owner/Admin/Trader roles enforced server-side.
- Owner-only user creation and Trader account assignment.
- Trader sessions are read-only for assigned account identifiers.
- PBKDF2 password hashing; minimum 12 characters.
- TOTP MFA supported and required by default for Owner/Admin creation.
- Session bearer token stored only as SHA-256 hash in SQLite.
- HttpOnly + Secure + SameSite=Strict session cookie.
- CSRF token required for authenticated mutation requests.
- Login and public lead submission rate limits.
- Session revocation and user suspension revoke sessions.
- Security event log records successful/failed logins and revocations.
- Private web service refuses a non-loopback bind; network exposure must be behind a TLS reverse proxy.
- Public Request Information remains separate and never creates a user.

## Deliberate boundary
The web/API application does **not** import or expose MT5 order-send, execution-gate, or trade-management mutation endpoints. Browser actions cannot directly send broker orders. Trading execution continues through the isolated v0.24.29 backend safety chain.

## Still not production-complete
- Final cloud deployment / TLS reverse proxy is not included here.
- Passkey/WebAuthn is not yet implemented; current admin MFA is TOTP.
- Final UI login form, password reset/recovery, email delivery and device trust workflows remain future staging work.
- Live account financial data adapters are not yet exposed through this API; current `/api/accounts` returns access metadata only.
- Real-money trading remains disabled/out of scope.
