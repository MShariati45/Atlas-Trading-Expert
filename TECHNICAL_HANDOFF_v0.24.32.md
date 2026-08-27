# Technical Handoff — Atlas v0.24.32

Scope: HTTPS/TLS reverse-proxy deployment boundary on top of v0.24.31 authenticated UI integration.

Security invariants:
- Python app binds loopback only.
- Public and private hosts are separated in application policy, not only proxy config.
- Public host can submit leads but cannot access private API routes.
- App host is required for authenticated APIs.
- Proxy headers are trusted only from loopback.
- Proxied mode cannot start without Secure cookies and proxy-trust enabled.
- Session cookie becomes host-only `__Host-atlas_session`.
- Private/API paths require forwarded HTTPS in proxied mode.
- Web/API still has no direct MT5 mutation path.

Deployment templates are examples; certificate email, server paths, DNS provider, and OS user must be set by the operator.
