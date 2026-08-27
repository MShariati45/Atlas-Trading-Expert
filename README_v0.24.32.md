# Atlas Trading Expert v0.24.32 — TLS Deployment Boundary

Adds a production-style staging boundary without exposing the Python application directly to the internet.

Highlights: strict public/app host separation, loopback reverse-proxy trust, mandatory Secure `__Host-` session cookie in proxied mode, HTTPS-forwarded-proto enforcement for private/API routes, unknown-Host rejection, HSTS/COOP/CORP security headers, CSP tightened by externalizing landing CSS/JS, Caddy/systemd/environment templates, deployment preflight, and regression tests.

This is still DEMO/STAGING. Real-money execution remains disabled.
