"""Atlas v0.23.6 M15-first read-only observer.

This launcher uses the four-symbol USDJPY replacement research profile, disables Fibonacci as an
entry gate, scans M15 in both directions, applies symbol/pattern-specific H4/H1
context only after a mature M15 trigger exists, and never sends orders.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime
from atlas.market_data.m15_strategy_runtime import M15FirstStrategyRuntime
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.trading_calendar import TradingCalendar
from atlas.strategy.profile import default_m15_first_profile


def _dump(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dump(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_dump(v) for v in obj]
    return obj


def main() -> int:
    ap=argparse.ArgumentParser(description="Atlas v0.23.6 M15-first read-only observer")
    ap.add_argument("--account-id", default="DEMO")
    ap.add_argument("--terminal-path", default=None)
    ap.add_argument("--login", type=int, default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--server", default=None)
    ap.add_argument("--state-file", default="runtime/atlas_m15_first_state.sqlite3")
    ap.add_argument("--output", default="dashboard/m15_first_state.json")
    ap.add_argument("--poll-seconds", type=float, default=15.0)
    args=ap.parse_args()

    profile=default_m15_first_profile()
    settings=MT5ConnectionSettings(terminal_path=args.terminal_path, login=args.login, password=args.password, server=args.server)
    feed=MT5MarketDataFeed({args.account_id:settings})
    account=AccountConfig(args.account_id,True,profile.risk_per_trade_pct,broker="MT5_DEMO")
    feed.connect(account)
    base=Path(__file__).resolve().parent
    htf=ReadOnlyAtlasRuntime(feed,base/args.state_file)
    strategy=M15FirstStrategyRuntime(feed,htf.store,profile=profile)
    calendar=TradingCalendar()
    out=base/args.output; out.parent.mkdir(parents=True,exist_ok=True)

    print(json.dumps({
        "mode":"READ_ONLY_M15_FIRST",
        "profile":profile.name,
        "watchlist":list(profile.watchlist),
        "fibonacci_gate":profile.fibonacci_enabled,
        "max_trades_per_day":profile.max_trades_per_day,
        "risk_per_trade_pct":profile.risk_per_trade_pct,
        "max_daily_risk_pct":profile.max_daily_risk_pct,
    },indent=2))

    try:
        while True:
            now=datetime.now(timezone.utc); cal=calendar.assess(now)
            symbols=[]
            for symbol in profile.watchlist:
                snap=htf.poll_symbol(symbol)
                item={
                    "symbol":symbol,
                    "h4":snap.h4,
                    "h1":snap.h1,
                    "entry_window_open":cal.new_entries_allowed,
                    "calendar_reasons":cal.reason_codes,
                }
                if cal.new_entries_allowed:
                    fib_pct=float((snap.fibonacci or {}).get("retracement_pct",0.0))
                    result=strategy.poll(symbol=symbol,h4_trend=str(snap.h4.get("effective_direction",snap.h4.get("trend","UNAVAILABLE"))),h1_trend=str(snap.h1.get("trend","UNAVAILABLE")),fib_pct=fib_pct)
                    item["m15_first"]=_dump(result)
                else:
                    item["m15_first"]={"entry_search_allowed":False,"reason_codes":cal.reason_codes}
                symbols.append(item)
            state={
                "schema_version":"2.0",
                "generated_at_utc":now.isoformat(),
                "mode":"READ_ONLY_M15_FIRST",
                "execution_enabled":False,
                "profile":profile.name,
                "fibonacci_gate_enabled":False,
                "watchlist":symbols,
            }
            tmp=out.with_suffix(out.suffix+".tmp")
            tmp.write_text(json.dumps(state,indent=2,default=str),encoding="utf-8"); tmp.replace(out)
            print(f"[{now.isoformat()}] refreshed {len(symbols)} symbols; entry_window={cal.new_entries_allowed}")
            time.sleep(max(2.0,args.poll_seconds))
    except KeyboardInterrupt:
        return 0
    finally:
        feed.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
