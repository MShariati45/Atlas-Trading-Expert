"""Collect approximately one year of read-only MT5 history for Atlas.

Run this on the Windows machine/VPS where MetaTrader 5 is installed and logged
into the demo account. This script DOES NOT send orders.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.market_data.historical_collector import MT5HistoricalCollector


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", default="config/demo_watchlist.json")
    ap.add_argument("--out", default="historical_data/one_year")
    ap.add_argument("--account-id", default="DEMO")
    ap.add_argument("--terminal-path", default=None)
    ap.add_argument("--login", type=int, default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--server", default=None)
    ap.add_argument("--start", default=None, help="UTC ISO timestamp override")
    ap.add_argument("--end", default=None, help="UTC ISO timestamp override")
    args = ap.parse_args()

    cfg = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    symbols = list(cfg["symbols"])
    settings = MT5ConnectionSettings(terminal_path=args.terminal_path, login=args.login, password=args.password, server=args.server)
    feed = MT5MarketDataFeed({args.account_id: settings})
    account = AccountConfig(args.account_id, True, float(cfg["risk"]["risk_per_trade_pct"]), float(cfg["management"]["target_r"]), "MT5_DEMO")
    feed.connect(account)
    try:
        collector = MT5HistoricalCollector(feed)
        if args.start and args.end:
            start = datetime.fromisoformat(args.start).astimezone(timezone.utc)
            end = datetime.fromisoformat(args.end).astimezone(timezone.utc)
        else:
            start, end = collector.one_year_window()
        manifest = collector.collect(account, symbols, args.out, start, end)
        print(json.dumps(asdict(manifest), indent=2))
    finally:
        feed.shutdown()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
