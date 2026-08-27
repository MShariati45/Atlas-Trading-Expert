# Atlas v0.24.32 TLS Deployment Boundary

## Objective
Expose only the public landing page and authenticated private application through HTTPS while the Python application remains bound to loopback. This remains DEMO/STAGING; real-money execution is disabled.

## DNS targets
- `atlastradingexpert.com` -> staging server public IP
- `www.atlastradingexpert.com` -> staging server public IP (redirects to apex)
- `app.atlastradingexpert.com` -> staging server public IP

Nameservers stay with the chosen DNS provider; Atlas needs DNS records, not custom nameservers, unless the user intentionally delegates DNS to a new provider.

## Required boundary
Internet -> Caddy/HTTPS :443 -> 127.0.0.1:8080 -> Atlas app

Do not expose port 8080 publicly.

## Host separation
- Public host: landing/static content + POST `/api/leads` only.
- App host: `/app/*`, authenticated `/api/*`, `/health`, shared static assets.
- Unknown Host headers are rejected.
- Public host cannot reach private APIs.

## Cookie/session requirements
`PROXY_STAGING` requires Secure cookies and uses the host-only `__Host-atlas_session` cookie. No Domain attribute is set. Owner/Admin MFA remains mandatory by default.

## Proxy trust
`X-Forwarded-For` / `X-Forwarded-Proto` are trusted only when the TCP peer is loopback. Direct clients cannot spoof their source IP or HTTPS state.

## Firewall
Allow inbound 80/443 only. Restrict SSH/RDP to administrator IP/VPN where possible. Deny public 8080.

## Deployment sequence
1. Copy package to staging host.
2. Create `/etc/atlas/atlas.env` from `deploy/atlas.env.example`.
3. Keep runtime databases/files owned only by the Atlas service user.
4. Install Caddy and adapt `deploy/Caddyfile.example`; replace the placeholder certificate email.
5. Install systemd service example and start Atlas on 127.0.0.1:8080.
6. Run `python run_deployment_preflight.py`.
7. Point DNS records to the server.
8. Verify TLS for apex and app subdomain.
9. Test Request Information, login/MFA, Trader isolation, Owner functions, logout, suspension, mobile layout.
10. Keep DEMO execution locked until market-open broker/news/preflight gates pass.
