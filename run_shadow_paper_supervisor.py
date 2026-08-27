"""Atlas v0.24.4 continuous shadow Paper Supervisor.

Read-only only: discovers M15 candidates, applies the frozen pair/pattern HTF rules,
then evaluates Supervisor gates including official scheduled news, static zones and
broker costs. It writes state/journal files and sends NO orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime
from atlas.market_data.m15_strategy_runtime import M15FirstStrategyRuntime
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.broker_cost_policy import load_broker_cost_policy
from atlas.services.live_news import LiveNewsGuardService
from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.services.paper_pipeline import LivePaperSupervisorPipeline
from atlas.services.trading_calendar import TradingCalendar
from atlas.strategy.profile import default_m15_first_profile
from atlas.supervisor.runtime import SupervisorRuntime

REQUIRED_NEWS_FAMILIES = (
    "USD_FOMC", "USD_EMPLOYMENT", "USD_CPI", "EUR_ECB", "CAD_BOC",
    "CAD_CPI", "CAD_LFS", "JPY_BOJ", "JPY_CPI", "JPY_LFS",
)


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _primitive(asdict(value))
    if isinstance(value, dict):
        return {str(k): _primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_primitive(v) for v in value]
    return str(value)


def _news_file_family_ok(path: Path) -> tuple[bool, list[str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, ["NEWS_FILE_UNREADABLE"]
    fam = raw.get("required_event_families", {})
    missing = [name for name in REQUIRED_NEWS_FAMILIES if fam.get(name) is not True]
    coverage_status = raw.get("coverage_status")
    reasons = []
    if coverage_status != "FULL_PRIMARY_BACKBONE":
        reasons.append("NEWS_COVERAGE_STATUS_NOT_FULL")
    reasons.extend(f"NEWS_FAMILY_MISSING:{name}" for name in missing)
    return not reasons, reasons


def _candidate_key(symbol: str, direction: str, package: dict[str, Any], decision: str) -> str:
    trigger = package.get("primary_trigger") or {}
    stable = {
        "symbol": symbol,
        "direction": direction,
        "decision": decision,
        "agent": trigger.get("agent"),
        "entry": trigger.get("entry_reference"),
        "stop": trigger.get("final_stop"),
        "event_time": trigger.get("event_time_utc") or trigger.get("trigger_time_utc") or trigger.get("time_utc"),
        "pattern": package.get("strategy_pattern"),
        "target_r": package.get("target_r"),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def main() -> int:
    ap = argparse.ArgumentParser(description="Atlas v0.24.4 read-only shadow Paper Supervisor")
    ap.add_argument("--account-id", default="DEMO")
    ap.add_argument("--terminal-path", default=None)
    ap.add_argument("--login", type=int, default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--server", default=None)
    ap.add_argument("--news-file", default="runtime/news_events.json")
    ap.add_argument("--cost-policy", default="config/broker_cost_policy.json")
    ap.add_argument("--state-file", default="runtime/atlas_shadow_supervisor_state.json")
    ap.add_argument("--journal", default="runtime/atlas_shadow_supervisor_journal.jsonl")
    ap.add_argument("--structure-state", default="runtime/atlas_m15_first_state.sqlite3")
    ap.add_argument("--poll-seconds", type=float, default=15.0)
    args = ap.parse_args()

    base = Path(__file__).resolve().parent
    profile = default_m15_first_profile()
    settings = MT5ConnectionSettings(
        login=args.login, password=args.password, server=args.server, terminal_path=args.terminal_path
    )
    feed = MT5MarketDataFeed({args.account_id: settings})
    account = AccountConfig(args.account_id, True, profile.risk_per_trade_pct, broker="MT5_DEMO")
    feed.connect(account)

    news_path = base / args.news_file
    family_ok, family_reasons = _news_file_family_ok(news_path)
    provider = JsonScheduledNewsProvider(
        news_path,
        strict_freshness=True,
        min_validity_seconds=30 * 60,
        strict_provenance=True,
        required_currencies={"USD", "EUR", "CAD", "JPY"},
        required_event_families=set(REQUIRED_NEWS_FAMILIES),
    )
    news = LiveNewsGuardService(provider) if family_ok else None

    cost_status = load_broker_cost_policy(base / args.cost_policy, profile.watchlist)
    limits = cost_status.limits_by_symbol if cost_status.approved else {}

    supervisor = SupervisorRuntime.from_strategy_profile(profile)
    htf = ReadOnlyAtlasRuntime(feed, base / args.structure_state)
    strategy = M15FirstStrategyRuntime(feed, htf.store, profile=profile, supervisor=supervisor)
    paper = LivePaperSupervisorPipeline(feed, news, supervisor=supervisor, market_limits_by_symbol=limits)
    calendar = TradingCalendar()

    state_path = base / args.state_file
    journal_path = base / args.journal
    state_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    last_logged: dict[str, str] = {}

    print(json.dumps({
        "mode": "READ_ONLY_SHADOW_PAPER_SUPERVISOR",
        "profile": profile.name,
        "watchlist": list(profile.watchlist),
        "execution_enabled": False,
        "news_family_coverage_ok": family_ok,
        "news_family_reasons": family_reasons,
        "broker_cost_policy_approved": cost_status.approved,
        "broker_cost_policy_mode": cost_status.mode,
        "execution_cost_validated": cost_status.execution_validated,
        "broker_cost_policy_reasons": list(cost_status.reason_codes),
        "expected_behavior": "WAIT on otherwise-valid candidates until broker-cost policy is explicitly approved" if not cost_status.approved else "paper gate evaluation enabled; execution remains locked and slippage unvalidated" if not cost_status.execution_validated else "paper gate evaluation with execution-validated costs; execution lock remains separate",
    }, indent=2))

    try:
        while True:
            now = datetime.now(timezone.utc)
            cal = calendar.assess(now)
            rows: list[dict[str, Any]] = []
            for symbol in profile.watchlist:
                snap = htf.poll_symbol(symbol)
                fib_pct = float((snap.fibonacci or {}).get("retracement_pct", 0.0))
                strategy_result = strategy.poll(
                    symbol=symbol,
                    h4_trend=str(snap.h4.get("effective_direction", snap.h4.get("trend", "UNAVAILABLE"))),
                    h1_trend=str(snap.h1.get("trend", "UNAVAILABLE")),
                    fib_pct=fib_pct,
                )
                symbol_row: dict[str, Any] = {
                    "symbol": symbol,
                    "h4": snap.h4,
                    "h1": snap.h1,
                    "entry_window_open": cal.new_entries_allowed,
                    "calendar_reasons": cal.reason_codes,
                    "directions": {},
                }
                for dr in (strategy_result.long, strategy_result.short):
                    drow: dict[str, Any] = {
                        "policy_allowed": dr.policy_allowed,
                        "policy_reason": dr.policy_reason,
                        "target_r": dr.target_r,
                    }
                    if dr.package and dr.package.get("coordination_state") == "READY_FOR_SUPERVISOR_REVIEW":
                        if dr.policy_allowed:
                            review = paper.review(
                                symbol=symbol,
                                direction=dr.direction,
                                package=dr.package,
                                alignment_ok=True,
                                fib_ok=True,  # Fibonacci is not an entry permission gate in this profile.
                                proposed_risk_pct=profile.risk_per_trade_pct,
                                now=now,
                            )
                            drow["paper_review"] = review.to_dict()
                            key = _candidate_key(symbol, dr.direction, dr.package, review.decision)
                            if last_logged.get(f"{symbol}:{dr.direction}") != key:
                                journal_record = {
                                    "observed_at_utc": now.isoformat(),
                                    "account_id": args.account_id,
                                    "symbol": symbol,
                                    "direction": dr.direction,
                                    "pattern": dr.package.get("strategy_pattern"),
                                    "target_r": dr.package.get("target_r"),
                                    "decision": review.decision,
                                    "reason_codes": review.reason_codes,
                                    "gates": review.gates,
                                    "entry": review.entry,
                                    "stop": review.stop,
                                    "target": review.target,
                                    "net_rr": review.net_rr,
                                    "market_costs": review.market_costs,
                                    "execution_enabled": False,
                                }
                                with journal_path.open("a", encoding="utf-8") as fh:
                                    fh.write(json.dumps(_primitive(journal_record), separators=(",", ":")) + "\n")
                                last_logged[f"{symbol}:{dr.direction}"] = key
                        else:
                            drow["paper_review"] = {
                                "decision": "REJECT_AT_PATTERN_POLICY",
                                "reason_codes": [dr.policy_reason],
                            }
                    symbol_row["directions"][dr.direction] = drow
                rows.append(symbol_row)

            state = {
                "schema_version": "1.0",
                "atlas_version": "0.24.4",
                "generated_at_utc": now.isoformat(),
                "mode": "READ_ONLY_SHADOW_PAPER_SUPERVISOR",
                "execution_enabled": False,
                "account_id": args.account_id,
                "profile": profile.name,
                "news": {
                    "path": str(news_path),
                    "family_coverage_ok": family_ok,
                    "family_reasons": family_reasons,
                    "provider_status": _primitive(provider.status),
                },
                "broker_cost_policy": {
                    "approved": cost_status.approved,
                    "mode": cost_status.mode,
                    "execution_validated": cost_status.execution_validated,
                    "reason_codes": list(cost_status.reason_codes),
                    "path": cost_status.source_path,
                },
                "supervisor": {
                    "mode": supervisor.mode.value,
                    "daily_ledger": _primitive(supervisor.ledger),
                },
                "watchlist": rows,
            }
            tmp = state_path.with_suffix(state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(_primitive(state), indent=2), encoding="utf-8")
            tmp.replace(state_path)
            print(f"[{now.isoformat()}] shadow supervisor refreshed {len(rows)} symbols; execution=LOCKED; cost_policy={cost_status.approved}")
            time.sleep(max(2.0, args.poll_seconds))
    except KeyboardInterrupt:
        return 0
    finally:
        feed.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
