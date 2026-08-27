from __future__ import annotations

import argparse
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import time
from urllib.parse import urlparse

from atlas.staging import LeadStore


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "web" / "public"
LEADS = LeadStore(ROOT / "runtime" / "leads.jsonl")
RATE: dict[str, deque[float]] = defaultdict(deque)
WINDOW_SECONDS = 300
MAX_SUBMISSIONS = 5


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"status": "ok", "mode": "STAGING", "execution": "LOCKED"})
        if path == "/app/login":
            body = b"<!doctype html><html><body style='background:#020912;color:white;font-family:Arial;padding:40px'><h1>Atlas Private Beta</h1><p>Client authentication is not enabled in this staging slice yet.</p><p>Demo execution remains locked.</p></body></html>"
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/leads":
            return self._json(404, {"error": "not found"})
        ip = self.client_address[0]
        now = time.time()
        q = RATE[ip]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= MAX_SUBMISSIONS:
            return self._json(429, {"error": "too many requests"})
        q.append(now)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("invalid request size")
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            lead = LEADS.submit(
                name=str(raw.get("name", "")), email=str(raw.get("email", "")),
                phone=str(raw.get("phone", "")), country=str(raw.get("country", "")),
                inquiry_type=str(raw.get("inquiry_type", "REQUEST_INFORMATION")),
                message=str(raw.get("message", "")),
            )
            return self._json(201, {"status": "received", "lead_id": lead.lead_id})
        except Exception as exc:
            return self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print("[staging-web]", self.address_string(), fmt % args)


def main() -> int:
    p = argparse.ArgumentParser(description="Atlas local staging landing-page server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Atlas staging web: http://{args.host}:{args.port}")
    print("DEMO/STAGING ONLY - execution remains locked")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
