from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime
from atlas.market_data.mt5_feed import MT5MarketDataFeed


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas MT5 read-only live observer")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--account-id", default="DEMO")
    parser.add_argument("--terminal-path", default=None)
    parser.add_argument("--login", type=int, default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--server", default=None)
    parser.add_argument("--state-file", default="runtime/atlas_state.sqlite3")
    args = parser.parse_args()

    settings = MT5ConnectionSettings(
        terminal_path=args.terminal_path,
        login=args.login,
        password=args.password,
        server=args.server,
    )
    feed = MT5MarketDataFeed({args.account_id: settings})
    account = AccountConfig(account_id=args.account_id, broker="MT5", enabled=True, risk_pct=0.5, target_r=2.0)
    feed.connect(account)
    try:
        runtime = ReadOnlyAtlasRuntime(feed, Path(args.state_file))
        snap = runtime.poll_symbol(args.symbol)
        print(json.dumps({
            "symbol": snap.symbol,
            "h4": snap.h4,
            "h1": snap.h1,
            "fibonacci": snap.fibonacci,
            "last_h4_bar": snap.last_h4_bar,
            "last_h1_bar": snap.last_h1_bar,
        }, indent=2))
    finally:
        feed.shutdown()


if __name__ == "__main__":
    main()
