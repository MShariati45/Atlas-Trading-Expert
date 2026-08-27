"""Atlas v0.24.34 supervised DEMO runtime preflight.

Read-only.  This command never imports an order transport and never sends an MT5
mutation.  It reports the independent safety prerequisites that must be true
before the supervised runtime may even attempt the existing controlled DEMO gate.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from atlas.execution.account_identity import AccountIdentityVerifier
from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.broker_cost_policy import load_broker_cost_policy
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.strategy.profile import default_m15_first_profile

ROOT = Path(__file__).resolve().parent


def _env_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def main() -> int:
    profile = default_m15_first_profile()
    account_id = os.getenv("ATLAS_MT5_ACCOUNT_ID", "ATLAS-DEMO").strip() or "ATLAS-DEMO"
    settings = MT5ConnectionSettings(
        terminal_path=os.getenv("ATLAS_MT5_TERMINAL_PATH") or None,
        login=_env_int("ATLAS_MT5_LOGIN"),
        password_env=os.getenv("ATLAS_MT5_PASSWORD_ENV", "ATLAS_MT5_PASSWORD"),
        server=os.getenv("ATLAS_MT5_SERVER") or None,
    )
    account = AccountConfig(account_id, True, profile.risk_per_trade_pct, broker="MT5_DEMO")
    feed = MT5MarketDataFeed({account_id: settings})
    checks: dict[str, bool] = {}
    detail: dict[str, object] = {}
    reasons: list[str] = []
    try:
        feed.connect(account)
        mt5 = feed._module()
        info = mt5.account_info()
        identity = AccountIdentityVerifier().from_mt5(account, info, mt5, expected_login=settings.login) if info is not None else None
        checks["mt5_connected"] = bool(info is not None and feed.terminal_health().get("terminal_connected"))
        checks["demo_identity_verified"] = bool(identity and identity.demo_verified)
        detail["identity"] = identity.to_dict() if identity else None
        if not checks["mt5_connected"]: reasons.append("MT5_NOT_CONNECTED")
        if not checks["demo_identity_verified"]: reasons.append("DEMO_IDENTITY_NOT_VERIFIED")
    except Exception as exc:
        checks["mt5_connected"] = False
        checks["demo_identity_verified"] = False
        detail["mt5_error"] = f"{type(exc).__name__}: {exc}"
        reasons.append("MT5_PREFLIGHT_FAILED")
    finally:
        try: feed.shutdown()
        except Exception: pass

    pf_path = ROOT / "runtime" / "demo_preflight_report.json"
    try:
        pf = json.loads(pf_path.read_text(encoding="utf-8"))
        checks["demo_preflight_ready"] = bool(pf.get("ready_for_paper_supervision") is True)
        detail["demo_preflight_generated_at_utc"] = pf.get("generated_at_utc")
    except Exception:
        checks["demo_preflight_ready"] = False
    if not checks["demo_preflight_ready"]: reasons.append("DEMO_PREFLIGHT_NOT_READY")

    cost = load_broker_cost_policy(ROOT / "config" / "broker_cost_policy.json", profile.watchlist)
    checks["broker_cost_policy_approved"] = bool(cost.approved)
    checks["execution_costs_validated"] = bool(cost.execution_validated)
    detail["broker_cost_policy_mode"] = cost.mode
    detail["broker_cost_policy_reasons"] = list(cost.reason_codes)
    if not cost.approved: reasons.append("BROKER_COST_POLICY_NOT_APPROVED")
    if not cost.execution_validated: reasons.append("SLIPPAGE_EXECUTION_COSTS_NOT_VALIDATED")

    baseline = ROOT / "runtime" / "adaptive_spread_baseline.json"
    checks["adaptive_spread_baseline_present"] = baseline.exists()
    if not baseline.exists(): reasons.append("ADAPTIVE_SPREAD_BASELINE_MISSING")

    news_path = ROOT / "runtime" / "news_events.json"
    news_ok = False
    news_detail: dict[str, object] = {}
    try:
        provider = JsonScheduledNewsProvider(news_path, strict_freshness=True, min_validity_seconds=30*60,
                                             strict_provenance=True, required_currencies={"USD","EUR","CAD","JPY"})
        provider.events(datetime.now(timezone.utc))
        news_ok = bool(provider.status.available)
        news_detail = {"available": provider.status.available, "event_count": provider.status.event_count,
                       "error": provider.status.error}
    except Exception as exc:
        news_detail = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    checks["news_guard_fresh"] = news_ok
    detail["news"] = news_detail
    if not news_ok: reasons.append("LIVE_NEWS_NOT_READY")

    approvals = H4HumanApprovalStore(ROOT / "runtime" / "h4_human_approvals.json")
    approved_symbols = []
    for symbol in profile.watchlist:
        row = approvals.dashboard_state(symbol, {})
        if str(row.get("status", "")).upper() in {"APPROVED", "VALID"}:
            approved_symbols.append(symbol)
    detail["h4_approved_symbols"] = approved_symbols
    checks["h4_approval_store_available"] = True

    switches = {
        "ATLAS_DEMO_EXECUTION": os.getenv("ATLAS_DEMO_EXECUTION", "").upper() == "YES",
        "enable_file": False,
    }
    enable_path = ROOT / "runtime" / "DEMO_EXECUTION_ENABLE.json"
    try:
        raw = json.loads(enable_path.read_text(encoding="utf-8"))
        switches["enable_file"] = raw.get("mode") == "DEMO_ONLY" and raw.get("enabled") is True
    except Exception:
        pass
    detail["execution_switches"] = switches
    checks["explicit_execution_switches"] = all(switches.values())
    if not checks["explicit_execution_switches"]: reasons.append("DEMO_EXECUTION_NOT_EXPLICITLY_ARMED")

    ready_for_observation = checks.get("mt5_connected", False) and checks.get("demo_identity_verified", False)
    ready_for_execution_attempt = all([
        ready_for_observation,
        checks.get("demo_preflight_ready", False),
        checks.get("broker_cost_policy_approved", False),
        checks.get("execution_costs_validated", False),
        checks.get("adaptive_spread_baseline_present", False),
        checks.get("news_guard_fresh", False),
        checks.get("explicit_execution_switches", False),
    ])
    report = {
        "atlas_version": "0.24.34",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "SUPERVISED_DEMO_PREFLIGHT_READ_ONLY",
        "checks": checks,
        "detail": detail,
        "ready_for_observation": ready_for_observation,
        "ready_for_execution_attempt": ready_for_execution_attempt,
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "note": "Even when ready_for_execution_attempt=true, every signal still must pass pattern policy, Supervisor, H4 approval, live news, adaptive spread, risk, idempotency, DEMO identity, broker order_check and post-fill verification.",
    }
    out = ROOT / "runtime" / "supervised_demo_preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)
    print(json.dumps(report, indent=2, default=str))
    return 0 if ready_for_observation else 2

if __name__ == "__main__":
    raise SystemExit(main())
