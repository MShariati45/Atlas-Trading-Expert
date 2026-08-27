from __future__ import annotations

import argparse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from atlas.api import AtlasPrivateAppService, AtlasReadModelService
from atlas.security import SQLiteAuthStore, SlidingWindowRateLimiter, DeploymentPolicy
from atlas.staging import LeadStore
from atlas.services.h4_human_approval import H4HumanApprovalStore

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "web" / "public"
AUTH = SQLiteAuthStore(ROOT / "runtime" / "atlas_auth.sqlite3")
LEADS = LeadStore(ROOT / "runtime" / "leads.jsonl")
READ_MODELS = AtlasReadModelService(dashboard_path=ROOT / "runtime" / "dashboard_state.json", execution_db=ROOT / "runtime" / "demo_execution.sqlite3")
H4_APPROVALS = H4HumanApprovalStore(ROOT / "runtime" / "h4_human_approvals.json")
APP = AtlasPrivateAppService(auth=AUTH, leads=LEADS, read_models=READ_MODELS, h4_approvals=H4_APPROVALS)
LOGIN_LIMIT = SlidingWindowRateLimiter(limit=8, window_seconds=300)
PUBLIC_LEAD_LIMIT = SlidingWindowRateLimiter(limit=5, window_seconds=300)
DEPLOYMENT = DeploymentPolicy.from_env()
SESSION_COOKIE = DEPLOYMENT.session_cookie_name


class Handler(SimpleHTTPRequestHandler):
    server_version = "AtlasStaging/0.24.32"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Permitted-Cross-Domain-Policies", "none")
        if DEPLOYMENT.proxied:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status: int, payload: dict, *, set_cookie: str | None = None) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, *, max_bytes: int = 32_768) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_bytes:
            raise ValueError("invalid request size")
        raw = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("JSON object required")
        return raw

    def _cookie_token(self) -> str:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def _user(self):
        return AUTH.resolve_session(self._cookie_token())

    def _require_user(self):
        user = self._user()
        if user is None:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
            return None
        return user

    def _require_csrf(self) -> bool:
        token = self._cookie_token()
        csrf = self.headers.get("X-Atlas-CSRF", "")
        if not AUTH.validate_csrf(token, csrf):
            self._json(HTTPStatus.FORBIDDEN, {"error": "CSRF validation failed"})
            return False
        return True

    def _client_ip(self) -> str:
        return DEPLOYMENT.client_ip(peer_ip=self.client_address[0], forwarded_for=self.headers.get("X-Forwarded-For", ""))

    def _deployment_guard(self, path: str) -> bool:
        host = self.headers.get("Host", "")
        if not DEPLOYMENT.route_allowed(host, self.command, path):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return False
        if DEPLOYMENT.proxied and (path.startswith("/app") or path.startswith("/api/")):
            if not DEPLOYMENT.request_is_https(peer_ip=self.client_address[0], forwarded_proto=self.headers.get("X-Forwarded-Proto", "")):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "HTTPS proxy boundary required"})
                return False
        return True

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self._deployment_guard(path):
            return
        if DEPLOYMENT.proxied and DEPLOYMENT.host_role(self.headers.get("Host", "")) == "APP" and path == "/":
            self.send_response(302); self.send_header("Location", "/app/"); self.end_headers(); return
        if path == "/health":
            return self._json(200, {"status": "ok", "mode": "STAGING", "execution": "LOCKED", "auth": "ENABLED"})
        if path in {"/app", "/app/", "/app/index.html"}:
            user = self._user()
            if user is None:
                self.send_response(302)
                self.send_header("Location", DEPLOYMENT.login_url())
                self.end_headers()
                return
            target = PUBLIC / "app" / "index.html"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if path == "/api/auth/me":
            user = self._require_user()
            if user is None:
                return
            return self._json(200, {"user": APP.identity_payload(user)})
        if path == "/api/dashboard":
            user = self._require_user()
            if user is None:
                return
            return self._json(200, {"dashboard": APP.dashboard(user)})
        if path == "/api/watchlist":
            user = self._require_user()
            if user is None:
                return
            return self._json(200, {"watchlist": APP.watchlist(user)})
        if path == "/api/accounts":
            user = self._require_user()
            if user is None:
                return
            return self._json(200, {"accounts": APP.list_account_summaries(user)})
        if path.startswith("/api/accounts/"):
            user = self._require_user()
            if user is None:
                return
            account_id = path.split("/", 3)[3]
            try:
                return self._json(200, {"account": APP.account_detail(user, account_id)})
            except PermissionError as exc:
                return self._json(403, {"error": str(exc)})
        if path == "/api/admin/users":
            user = self._require_user()
            if user is None:
                return
            try:
                return self._json(200, {"users": APP.list_users(user)})
            except PermissionError as exc:
                return self._json(403, {"error": str(exc)})
        if path == "/api/leads":
            user = self._require_user()
            if user is None:
                return
            try:
                return self._json(200, {"leads": APP.list_leads(user)})
            except PermissionError as exc:
                return self._json(403, {"error": str(exc)})
        if path == "/api/security/events":
            user = self._require_user()
            if user is None:
                return
            if user.role.value != "OWNER":
                return self._json(403, {"error": "owner role required"})
            return self._json(200, {"events": AUTH.list_security_events(limit=200)})
        if path == "/app/login":
            target = PUBLIC / "app" / "login.html"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._deployment_guard(path):
            return
        ip = self._client_ip()
        try:
            if path == "/api/leads":
                if not PUBLIC_LEAD_LIMIT.allow(ip):
                    return self._json(429, {"error": "too many requests"})
                raw = self._read_json(max_bytes=16_384)

                risk_accepted = raw.get("risk_disclosure_accepted") is True
                privacy_accepted = raw.get("privacy_consent_accepted") is True

                if not risk_accepted:
                    return self._json(400, {"error": "risk disclosure acceptance required"})

                if not privacy_accepted:
                    return self._json(400, {"error": "privacy acknowledgement required"})

                lead = LEADS.submit(
                    name=str(raw.get("name", "")),
                    email=str(raw.get("email", "")),
                    phone=str(raw.get("phone", "")),
                    country=str(raw.get("country", "")),
                    inquiry_type=str(raw.get("inquiry_type", "REQUEST_INFORMATION")),
                    message=str(raw.get("message", "")),
                    risk_disclosure_accepted=True,
                    risk_disclosure_version="ATLAS-RISK-2026-08-v1.0",
                    privacy_consent_accepted=True,
                    privacy_policy_version="ATLAS-PRIVACY-2026-08-v1.0",
                    request_source=str(raw.get("request_source", "PUBLIC_REQUEST_INFORMATION")),
                )
                return self._json(201, {"status": "received", "lead_id": lead.lead_id})
            if path == "/api/auth/login":
                if not LOGIN_LIMIT.allow(ip):
                    return self._json(429, {"error": "too many login attempts"})
                raw = self._read_json(max_bytes=8_192)
                session = AUTH.authenticate(
                    username=str(raw.get("username", "")), password=str(raw.get("password", "")), mfa_code=str(raw.get("mfa_code", "")),
                    ip=ip, user_agent=self.headers.get("User-Agent", ""),
                )
                if session is None:
                    return self._json(401, {"error": "invalid credentials or MFA"})
                secure = "; Secure" if DEPLOYMENT.cookie_secure else ""
                cookie = f"{SESSION_COOKIE}={session.token}; Path=/; HttpOnly; SameSite=Strict{secure}; Max-Age=28800"
                return self._json(200, {"status": "authenticated", "csrf_token": session.csrf_token, "user": APP.identity_payload(session.user)}, set_cookie=cookie)
            if path == "/api/auth/logout":
                user = self._require_user()
                if user is None or not self._require_csrf():
                    return
                AUTH.revoke_session(self._cookie_token())
                return self._json(200, {"status": "logged_out"}, set_cookie=f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict{'; Secure' if DEPLOYMENT.cookie_secure else ''}; Max-Age=0")
            if path == "/api/admin/users":
                user = self._require_user()
                if user is None or not self._require_csrf():
                    return
                raw = self._read_json()
                created = APP.create_user(user, username=str(raw.get("username", "")), password=str(raw.get("password", "")), role=str(raw.get("role", "TRADER")), account_ids=list(raw.get("account_ids", [])), mfa_secret_hex=str(raw.get("mfa_secret_hex", "")))
                return self._json(201, {"user": created})
            if path == "/api/admin/assign-account":
                user = self._require_user()
                if user is None or not self._require_csrf():
                    return
                raw = self._read_json()
                updated = APP.assign_account(user, trader_user_id=str(raw.get("trader_user_id", "")), account_id=str(raw.get("account_id", "")))
                return self._json(200, {"user": updated})
            if path == "/api/admin/user-status":
                user = self._require_user()
                if user is None or not self._require_csrf():
                    return
                raw = self._read_json()
                updated = APP.set_user_enabled(user, user_id=str(raw.get("user_id", "")), enabled=bool(raw.get("enabled", False)))
                return self._json(200, {"user": updated})
            if path == "/api/h4/approve":
                user = self._require_user()
                if user is None or not self._require_csrf():
                    return
                raw = self._read_json()
                def num(name):
                    value = raw.get(name)
                    return None if value in (None, "") else float(value)
                approval = APP.approve_h4(user, symbol=str(raw.get("symbol", "")), trend=str(raw.get("trend", "")),
                                          impulse_start=num("impulse_start"), impulse_end=num("impulse_end"),
                                          note=str(raw.get("note", "")), structure_token=raw.get("structure_token"))
                return self._json(200, {"approval": approval})
            return self._json(404, {"error": "not found"})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc)})
        except (ValueError, KeyError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception:
            # Never leak stack traces/details over the API boundary.
            return self._json(500, {"error": "internal server error"})

    def log_message(self, fmt: str, *args) -> None:
        print("[secure-staging-web]", self.address_string(), fmt % args)


def main() -> int:
    p = argparse.ArgumentParser(description="Atlas secure private-app API behind a loopback TLS reverse proxy")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing non-loopback bind. Use a TLS reverse proxy for network exposure.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Atlas secure staging web: http://{args.host}:{args.port}")
    print("DEMO/STAGING ONLY - REAL MONEY DISABLED")
    print(f"Deployment mode: {DEPLOYMENT.mode}; public={DEPLOYMENT.public_host}; app={DEPLOYMENT.app_host}")
    print("Loopback-only application server. Public exposure must terminate TLS at the reverse proxy.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
