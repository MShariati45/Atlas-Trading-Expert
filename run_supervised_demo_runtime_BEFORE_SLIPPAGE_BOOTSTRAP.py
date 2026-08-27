"""Atlas v0.24.34 supervised DEMO runtime.

Default mode is observation-only.  The process can reach the existing order
transport only when BOTH the command-line --allow-execution flag and the frozen
DemoExecutionAuthorizer local switches are present.  A PAPER_ONLY broker-cost
policy can never execute: execution requires execution_validated slippage/costs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.demo_runtime import DemoExecutionRuntime
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.mt5_bridge import MT5ConnectionSettings, MT5PythonBridge
from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime
from atlas.market_data.m15_strategy_runtime import M15FirstStrategyRuntime
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.broker_cost_policy import load_broker_cost_policy
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.services.live_news import LiveNewsGuardService
from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.services.paper_pipeline import LivePaperSupervisorPipeline
from atlas.services.trading_calendar import TradingCalendar
from atlas.strategy.profile import default_m15_first_profile
from run_dashboard_activation import build_live, _atomic_write

ROOT = Path(__file__).resolve().parent
SUPERVISED_STATE = ROOT / "runtime" / "supervised_demo_state.json"
STRUCTURE_DB = ROOT / "runtime" / "atlas_supervised_demo_runtime.sqlite3"
LEDGER_DB = ROOT / "runtime" / "demo_execution.sqlite3"


def _env_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _signal_from_package(symbol: str, direction: str, pkg: dict[str, Any]) -> ApprovedSignal | None:
    t = pkg.get("primary_trigger") or {}
    entry, stop = t.get("entry_reference"), t.get("final_stop")
    if entry is None or stop is None:
        return None
    entry, stop = float(entry), float(stop)
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target_r = float(pkg.get("target_r", 2.0) or 2.0)
    target = entry + target_r * risk if direction.upper() == "LONG" else entry - target_r * risk
    stable = {
        "symbol": symbol.upper(), "direction": direction.upper(),
        "event_id": t.get("event_id"), "trigger_time": t.get("trigger_time"),
        "entry": entry, "stop": stop, "target": target,
        "pattern": pkg.get("strategy_pattern"),
    }
    signal_id = "SIG-" + hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:20].upper()
    return ApprovedSignal(signal_id, symbol.upper(), direction.upper(), entry, stop, target)


def main() -> int:
    ap = argparse.ArgumentParser(description="Atlas v0.24.34 supervised DEMO runtime")
    ap.add_argument("--poll-seconds", type=float, default=float(os.getenv("ATLAS_SUPERVISED_POLL_SECONDS", "15")))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--allow-execution", action="store_true", help="permit reaching the controlled DEMO gate; all local hard locks still apply")
    args = ap.parse_args()

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
    approvals = H4HumanApprovalStore(ROOT / "runtime" / "h4_human_approvals.json")
    authorizer = DemoExecutionAuthorizer(
        approval_store=approvals,
        enable_file=ROOT / "runtime" / "DEMO_EXECUTION_ENABLE.json",
        preflight_file=ROOT / "runtime" / "demo_preflight_report.json",
    )

    news_path = ROOT / "runtime" / "news_events.json"
    provider = JsonScheduledNewsProvider(news_path, strict_freshness=True, min_validity_seconds=30*60,
                                         strict_provenance=True, required_currencies={"USD","EUR","CAD","JPY"})
    news = LiveNewsGuardService(provider)
    cost = load_broker_cost_policy(ROOT / "config" / "broker_cost_policy.json", profile.watchlist)
    limits = cost.limits_by_symbol if cost.approved else {}
    spread = AdaptiveSpreadGuard.from_file(ROOT / "runtime" / "adaptive_spread_baseline.json") if (ROOT / "runtime" / "adaptive_spread_baseline.json").exists() else AdaptiveSpreadGuard({"symbols": {}})

    exec_bridge = MT5PythonBridge({account_id: settings}, execution_enabled=bool(args.allow_execution))
    execution = DemoExecutionRuntime(bridge=exec_bridge, authorizer=authorizer, spread_guard=spread,
                                     news_service=news, ledger_path=LEDGER_DB)

    feed.connect(account)
    htf = ReadOnlyAtlasRuntime(feed, STRUCTURE_DB)
    strategy = M15FirstStrategyRuntime(feed, htf.store, profile=profile)
    calendar = TradingCalendar()
    paper = LivePaperSupervisorPipeline(feed, news, market_limits_by_symbol=limits,
                                       adaptive_spread_baseline_path=str(ROOT / "runtime" / "adaptive_spread_baseline.json"))

    print(json.dumps({
        "atlas_version": "0.24.34",
        "mode": "SUPERVISED_DEMO_OBSERVATION" if not args.allow_execution else "SUPERVISED_DEMO_EXECUTION_ATTEMPT_ENABLED",
        "allow_execution_flag": bool(args.allow_execution),
        "cost_policy_mode": cost.mode,
        "execution_costs_validated": cost.execution_validated,
        "execution_transport_enabled": bool(exec_bridge.execution_enabled),
        "real_money": "FORBIDDEN",
    }, indent=2))

    try:
        while True:
            now = datetime.now(timezone.utc)
            base_state = build_live(feed, account, htf, strategy, calendar, approvals, profile.watchlist)
            candidates: list[dict[str, Any]] = []
            executions: list[dict[str, Any]] = []
            global_blockers: list[str] = []
            if not args.allow_execution: global_blockers.append("PROCESS_OBSERVATION_ONLY")
            if not cost.approved: global_blockers.append("BROKER_COST_POLICY_NOT_APPROVED")
            if not cost.execution_validated: global_blockers.append("SLIPPAGE_EXECUTION_COSTS_NOT_VALIDATED")
            try:
                provider.events(now)
                if not provider.status.available: global_blockers.append("LIVE_NEWS_NOT_READY")
            except Exception:
                global_blockers.append("LIVE_NEWS_NOT_READY")

            for row in base_state.get("watchlist", []):
                symbol = str(row.get("symbol", ""))
                h4 = str(row.get("h4_effective_direction", row.get("h4_trend", "UNAVAILABLE")))
                h1 = str(row.get("h1_trend", "UNAVAILABLE"))
                try:
                    snap = htf.poll_symbol(symbol)
                    fib_pct = float((snap.fibonacci or {}).get("retracement_pct", 0.0) or 0.0)
                    sr = strategy.poll(symbol=symbol, h4_trend=h4, h1_trend=h1, fib_pct=fib_pct)
                except Exception as exc:
                    candidates.append({"symbol": symbol, "status": "WAIT", "reasons": [f"STRATEGY_RUNTIME_ERROR:{type(exc).__name__}"]})
                    continue
                for side in (sr.long, sr.short):
                    pkg = side.package
                    if not pkg or pkg.get("coordination_state") != "READY_FOR_SUPERVISOR_REVIEW":
                        continue
                    if not side.policy_allowed:
                        candidates.append({"symbol": symbol, "direction": side.direction, "status": "POLICY_BLOCKED", "reasons": [side.policy_reason]})
                        continue
                    review = paper.review(symbol=symbol, direction=side.direction, package=pkg,
                                          alignment_ok=True, fib_ok=True,
                                          proposed_risk_pct=profile.risk_per_trade_pct, now=now)
                    signal = _signal_from_package(symbol, side.direction, pkg)
                    crow = {
                        "symbol": symbol, "direction": side.direction,
                        "pattern": pkg.get("strategy_pattern"), "paper_decision": review.decision,
                        "paper_reasons": review.reason_codes, "entry": review.entry, "stop": review.stop,
                        "target": review.target, "net_rr": review.net_rr,
                        "signal_id": signal.signal_id if signal else None,
                    }
                    if review.decision != "APPROVE":
                        crow["status"] = "SUPERVISOR_" + review.decision
                        candidates.append(crow)
                        continue
                    if signal is None:
                        crow["status"] = "BLOCKED"; crow["execution_reasons"] = ["SIGNAL_GEOMETRY_UNAVAILABLE"]
                        candidates.append(crow); continue
                    blockers = list(global_blockers)
                    if blockers:
                        crow["status"] = "READY_BUT_EXECUTION_LOCKED"
                        crow["execution_reasons"] = blockers
                        candidates.append(crow)
                        continue
                    try:
                        account_state = execution.authorize_account(account, safety_passed=True, explicit_demo_unlock=True)
                        gate = execution.prepare(account, account_state, signal, now=now)
                        crow["gate"] = gate.to_dict()
                        if gate.allowed and gate.ticket is not None:
                            result = execution.execute(account, account_state, signal, gate)
                            executions.append({"signal_id": signal.signal_id, "symbol": symbol, "direction": side.direction,
                                               "result": result.to_dict()})
                            crow["status"] = "EXECUTION_" + result.status
                        else:
                            crow["status"] = "CONTROLLED_GATE_BLOCKED"
                    except Exception as exc:
                        crow["status"] = "EXECUTION_BLOCKED"
                        crow["execution_reasons"] = [f"{type(exc).__name__}:{exc}"]
                    candidates.append(crow)

            readiness = {
                "allow_execution_flag": bool(args.allow_execution),
                "cost_policy_approved": bool(cost.approved),
                "cost_policy_mode": cost.mode,
                "execution_costs_validated": bool(cost.execution_validated),
                "news_available": bool(getattr(provider.status, "available", False)),
                "global_blockers": list(dict.fromkeys(global_blockers)),
                "execution_transport_enabled": bool(exec_bridge.execution_enabled),
            }
            supervised = {
                "schema_version": "1.0", "atlas_version": "0.24.34", "generated_at_utc": now.isoformat(),
                "mode": "SUPERVISED_DEMO_OBSERVATION" if not args.allow_execution else "SUPERVISED_DEMO_EXECUTION_ATTEMPT_ENABLED",
                "account_id": account_id, "readiness": readiness, "candidates": candidates,
                "executions_this_cycle": executions, "real_money": "FORBIDDEN",
            }
            _atomic(SUPERVISED_STATE, supervised)
            base_state["atlas_version"] = "0.24.34"
            base_state["supervised_demo"] = supervised
            base_state["execution_enabled"] = bool(args.allow_execution and not readiness["global_blockers"])
            _atomic_write(base_state)
            print(f"[{now.isoformat()}] supervised DEMO refreshed; candidates={len(candidates)}; executions={len(executions)}; execution={'ARMED' if base_state['execution_enabled'] else 'LOCKED'}")
            if args.once: break
            time.sleep(max(2.0, args.poll_seconds))
    except KeyboardInterrupt:
        return 0
    finally:
        feed.shutdown()
        try: exec_bridge._module().shutdown()
        except Exception: pass
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
