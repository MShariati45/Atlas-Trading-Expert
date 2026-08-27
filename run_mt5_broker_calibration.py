"""Atlas v0.24.22 read-only broker spread calibration collector.

Collects tick/spread observations only. It NEVER sends orders and therefore cannot
measure real execution slippage; slippage remains pending until a later explicitly
approved demo-execution phase.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.services.broker_calibration import summarize_spreads
from atlas.strategy.profile import default_m15_first_profile


def parse_map(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"Invalid --symbol-map {raw!r}; use CANONICAL=BROKER")
        a, b = (x.strip() for x in raw.split("=", 1))
        out[a.upper()] = b
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only Atlas broker spread calibration")
    p.add_argument("--account-id", default="DEMO")
    p.add_argument("--terminal-path", default=None)
    p.add_argument("--login", type=int, default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--server", default=None)
    p.add_argument("--symbol-map", action="append", default=[])
    p.add_argument("--duration-minutes", type=float, default=60.0)
    p.add_argument("--interval-seconds", type=float, default=5.0)
    p.add_argument("--csv", default="runtime/broker_spread_samples.csv")
    p.add_argument("--summary", default="runtime/broker_calibration_summary.json")
    args = p.parse_args()
    if args.duration_minutes <= 0 or args.interval_seconds <= 0:
        raise SystemExit("duration and interval must be positive")

    profile = default_m15_first_profile()
    settings = MT5ConnectionSettings(
        login=args.login, password=args.password, server=args.server,
        terminal_path=args.terminal_path, symbol_map=parse_map(args.symbol_map),
    )
    feed = MT5MarketDataFeed({args.account_id: settings})
    acct = AccountConfig(args.account_id, True, profile.risk_per_trade_pct)
    csv_path = Path(args.csv); csv_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary); summary_path.parent.mkdir(parents=True, exist_ok=True)
    samples: dict[str, list[float]] = defaultdict(list)
    started = datetime.now(timezone.utc)
    end_at = time.monotonic() + args.duration_minutes * 60.0
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    try:
        feed.connect(acct)
        snap = feed.account_snapshot()
        if args.login is not None and snap.login != args.login:
            raise RuntimeError(f"ACCOUNT_LOGIN_MISMATCH expected={args.login} actual={snap.login}")
        with csv_path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["utc_time","vancouver_time","account_id","login","symbol","broker_symbol","bid","ask","point","spread_points","tick_age_seconds"])
            if write_header: w.writeheader()
            while time.monotonic() < end_at:
                now = datetime.now(timezone.utc)
                for symbol in profile.watchlist:
                    meta = feed.ensure_symbol(symbol)
                    tick = feed.tick(symbol)
                    spread = tick.spread_price / meta.point if meta.point > 0 else 0.0
                    age = max(0.0, (now - tick.time_utc).total_seconds())
                    samples[symbol].append(spread)
                    w.writerow({
                        "utc_time": now.isoformat(),
                        "vancouver_time": now.astimezone(ZoneInfo("America/Vancouver")).isoformat(),
                        "account_id": args.account_id,
                        "login": snap.login,
                        "symbol": symbol,
                        "broker_symbol": meta.symbol,
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "point": meta.point,
                        "spread_points": spread,
                        "tick_age_seconds": age,
                    })
                fh.flush()
                time.sleep(args.interval_seconds)
    finally:
        feed.shutdown()

    payload = {
        "atlas_version": "0.24.22",
        "mode": "READ_ONLY_BROKER_CALIBRATION",
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "duration_minutes_requested": args.duration_minutes,
        "interval_seconds": args.interval_seconds,
        "symbols": {s: summarize_spreads(samples[s]).to_dict() for s in profile.watchlist},
        "important": [
            "No orders were sent.",
            "Observed spread is not the same as execution slippage.",
            "No spread/slippage limits are activated automatically from this file.",
        ],
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Samples: {csv_path}")
    print(f"Summary: {summary_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
