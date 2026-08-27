from __future__ import annotations
from pathlib import Path
import os
import sys

from atlas.security.deployment import DeploymentPolicy

ROOT = Path(__file__).resolve().parent
checks = {}
try:
    p = DeploymentPolicy.from_env()
    checks['deployment_policy'] = p.proxied
    checks['distinct_hosts'] = p.public_host != p.app_host
    checks['secure_cookie'] = p.cookie_secure and p.session_cookie_name.startswith('__Host-')
    checks['trusted_proxy'] = p.trust_proxy
except Exception as exc:
    print('DEPLOYMENT_POLICY_ERROR:', exc)
    raise SystemExit(2)
checks['caddy_template'] = (ROOT/'deploy'/'Caddyfile.example').exists()
checks['service_template'] = (ROOT/'deploy'/'atlas-web.service.example').exists()
checks['landing_assets_external'] = (ROOT/'web/public/landing.css').exists() and (ROOT/'web/public/landing.js').exists()
checks['demo_only_marker'] = 'REAL MONEY DISABLED' in (ROOT/'web/public/app/index.html').read_text(encoding='utf-8')
for k,v in checks.items(): print(f'{k}: {"PASS" if v else "FAIL"}')
ok=all(checks.values())
print('deployment_boundary_ready:', ok)
raise SystemExit(0 if ok else 1)
