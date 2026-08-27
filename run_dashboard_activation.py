"""Atlas v0.24.33 authenticated dashboard activation runtime.

Read-only MT5 observation service for the private Owner dashboard.  It writes
runtime/dashboard_state.json atomically and NEVER imports an order transport.
It also refuses to publish a connected account as usable unless MT5 trade_mode
is positively verified as DEMO by AccountIdentityVerifier.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.execution.account_identity import AccountIdentityVerifier
from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime
from atlas.market_data.m15_strategy_runtime import M15FirstStrategyRuntime
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.services.trading_calendar import TradingCalendar
from atlas.strategy.profile import default_m15_first_profile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "runtime" / "dashboard_state.json"
STATE_DB = ROOT / "runtime" / "atlas_dashboard_runtime.sqlite3"


def _env_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


def _safe_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _safe_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _safe_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_safe_dict(v) for v in obj]
    return obj


def _atomic_write(state: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(OUT)


def _placeholder_state(message: str, *, account_id: str, symbols: tuple[str, ...]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for s in symbols:
        rows.append({
            "symbol": s, "bid": None, "ask": None, "spread_points": None,
            "h4_trend": "WAITING_FOR_MT5", "h4_effective_direction": "WAITING_FOR_MT5",
            "h4_phase": "UNAVAILABLE", "h1_trend": "WAITING_FOR_MT5", "h1_phase": "UNAVAILABLE",
            "alignment": "UNAVAILABLE", "coordinator": "IDLE", "supervisor": "WAIT",
            "supervisor_reason": message, "error": message,
            "h4_human_approval": {"status": "REVIEW_REQUIRED"},
        })
    return {
        "schema_version": "3.0", "generated_at_utc": now, "mode": "DASHBOARD_ACTIVATION_WAITING_FOR_MT5",
        "execution_enabled": False,
        "terminal": {"terminal_connected": False, "connected_account_id": account_id, "error": message},
        "account": {"account_id": account_id, "status": "UNAVAILABLE", "demo_verified": False, "error": message},
        "open_positions": [], "watchlist": rows,
        "summary": {"symbols": len(rows), "errors": list(symbols), "open_positions": 0,
                    "news_guard": "PENDING_RUNTIME", "static_zones": "PENDING_RUNTIME",
                    "api_mode": "PERSISTED_READ_MODEL", "risk_per_trade_pct": 0.5,
                    "max_daily_risk_pct": 1.0, "max_trades_per_day": 2},
    }


def build_live(feed: MT5MarketDataFeed, account: AccountConfig, htf: ReadOnlyAtlasRuntime,
               strategy: M15FirstStrategyRuntime, calendar: TradingCalendar,
               approvals: H4HumanApprovalStore, symbols: tuple[str, ...]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    mt5 = feed._module()
    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
    identity = AccountIdentityVerifier().from_mt5(account, info, mt5)
    if not identity.demo_verified:
        raise PermissionError("DEMO identity verification failed: " + ",".join(identity.reasons))

    acct = feed.snapshot_dict(feed.account_snapshot())
    acct.update({"account_id": account.account_id, "demo_verified": True,
                 "identity_reasons": list(identity.reasons), "trade_mode": identity.trade_mode,
                 "status": "CONNECTED_DEMO"})
    terminal = feed.terminal_health()
    terminal["demo_verified"] = True
    cal = calendar.assess(now)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for symbol in symbols:
        try:
            snap = htf.poll_symbol(symbol)
            tick = feed.tick(symbol)
            meta = feed.ensure_symbol(symbol)
            approval = approvals.dashboard_state(symbol, snap.h4)
            raw_h4 = str(snap.h4.get("effective_direction", snap.h4.get("trend", "UNAVAILABLE")))
            h4 = str(approval.get("approved_trend") if approval.get("execution_authorized_directionally") else raw_h4)
            h1 = str(snap.h1.get("trend", "UNAVAILABLE"))
            fib_pct = float((snap.fibonacci or {}).get("retracement_pct", 0.0) or 0.0)
            strat = strategy.poll(symbol=symbol, h4_trend=h4, h1_trend=h1, fib_pct=fib_pct) if cal.new_entries_allowed else None
            ready = []
            coordinator = "IDLE"
            supervisor = "WAIT"
            reason = "; ".join(cal.reason_codes) if not cal.new_entries_allowed else "No mature M15 package yet."
            if strat is not None:
                for side in (strat.long, strat.short):
                    if side.package and side.package.get("coordination_state") == "READY_FOR_SUPERVISOR_REVIEW":
                        ready.append({"direction": side.direction, "allowed": side.policy_allowed,
                                      "reason": side.policy_reason, "target_r": side.target_r,
                                      "package": _safe_dict(side.package)})
                if ready:
                    coordinator = "READY_FOR_SUPERVISOR_REVIEW"
                    allowed = [x for x in ready if x["allowed"]]
                    supervisor = "DEMO_CANDIDATE" if allowed else "POLICY_BLOCKED"
                    reason = allowed[0]["reason"] if allowed else ready[0]["reason"]
            point = meta.point if meta.point > 0 else 1.0
            approval = approvals.dashboard_state(symbol, snap.h4)
            rows.append({
                "symbol": symbol, "bid": tick.bid, "ask": tick.ask,
                "spread_points": tick.spread_price / point,
                "h4_trend": str(snap.h4.get("trend", "UNAVAILABLE")),
                "h4_effective_direction": h4, "h4_phase": str(snap.h4.get("phase", "UNAVAILABLE")),
                "h1_trend": h1, "h1_phase": str(snap.h1.get("phase", "UNAVAILABLE")),
                "alignment": "OPPOSED" if h4 in {"BULLISH","BEARISH"} and h1 in {"BULLISH","BEARISH"} and h4 != h1 else ("ALIGNED" if h4 == h1 else "TRANSITION"),
                "coordinator": coordinator, "supervisor": supervisor, "supervisor_reason": reason,
                "last_h4_bar": snap.last_h4_bar, "last_h1_bar": snap.last_h1_bar,
                "entry_window_open": cal.new_entries_allowed, "calendar_reasons": list(cal.reason_codes),
                "m15_ready_packages": ready, "h4_human_approval": approval, "error": None,
            })
        except Exception as exc:
            errors.append(symbol)
            rows.append({"symbol": symbol, "bid": None, "ask": None, "spread_points": None,
                         "h4_trend": "ERROR", "h4_effective_direction": "ERROR", "h4_phase": "ERROR",
                         "h1_trend": "ERROR", "h1_phase": "ERROR", "alignment": "UNKNOWN",
                         "coordinator": "IDLE", "supervisor": "WAIT", "supervisor_reason": "Read-only observation error.",
                         "h4_human_approval": {"status": "REVIEW_REQUIRED"}, "error": str(exc)})
    positions = feed.positions()
    return {
        "schema_version": "3.0", "generated_at_utc": now.isoformat(), "mode": "READ_ONLY_DEMO_OBSERVATION",
        "execution_enabled": False, "terminal": terminal, "account": acct, "open_positions": positions,
        "watchlist": rows,
        "summary": {"symbols": len(rows), "errors": errors, "open_positions": len(positions),
                    "news_guard": "PENDING_EXECUTION_RUNTIME", "static_zones": "PERSISTED_STRATEGY_RUNTIME",
                    "api_mode": "EVENT_DRIVEN_PERSISTED_STATE", "risk_per_trade_pct": 0.5,
                    "max_daily_risk_pct": 1.0, "max_trades_per_day": 2,
                    "entry_window_open": cal.new_entries_allowed, "calendar_reasons": list(cal.reason_codes)},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Atlas v0.24.33 read-only Owner dashboard activation")
    ap.add_argument("--once", action="store_true", help="write one snapshot and exit")
    ap.add_argument("--poll-seconds", type=float, default=float(os.getenv("ATLAS_DASHBOARD_POLL_SECONDS", "15")))
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

    try:
        feed.connect(account)
        htf = ReadOnlyAtlasRuntime(feed, STATE_DB)
        strategy = M15FirstStrategyRuntime(feed, htf.store, profile=profile)
        calendar = TradingCalendar()
        while True:
            try:
                state = build_live(feed, account, htf, strategy, calendar, approvals, profile.watchlist)
            except Exception as exc:
                state = _placeholder_state(str(exc), account_id=account_id, symbols=profile.watchlist)
            _atomic_write(state)
            print(f"[{state['generated_at_utc']}] dashboard snapshot: {state['mode']}; execution=LOCKED")
            if args.once:
                break
            time.sleep(max(5.0, args.poll_seconds))
    except Exception as exc:
        state = _placeholder_state(str(exc), account_id=account_id, symbols=profile.watchlist)
        _atomic_write(state)
        print("Atlas dashboard waiting for MT5 configuration:", exc)
        return 2
    finally:
        feed.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

