"""Atlas v0.24.19 MT5 demo preflight (strictly read-only).

Examples on the Windows PC/VPS with MT5 installed and logged in:
  python run_mt5_demo_probe.py --login 123456 --server "Broker-Demo"
  python run_mt5_demo_probe.py --symbol-map XAUUSD=XAUUSD.a --symbol-map EURUSD=EURUSD.a
  python run_mt5_demo_probe.py --news-json runtime/news_events.json --require-paper-ready

No order, stop modification, or close request can be sent by this script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas.execution.demo_validator import MT5DemoValidator
from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.strategy.profile import default_m15_first_profile


def _parse_symbol_map(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"Invalid --symbol-map '{raw}'. Expected CANONICAL=BROKER_SYMBOL")
        canonical, broker = (x.strip() for x in raw.split("=", 1))
        if not canonical or not broker:
            raise ValueError(f"Invalid --symbol-map '{raw}'")
        out[canonical.upper()] = broker
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas MT5 read-only demo readiness preflight")
    parser.add_argument("--account-id", default="DEMO")
    parser.add_argument("--terminal-path", default=None)
    parser.add_argument("--login", type=int, default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--server", default=None)
    parser.add_argument("--symbol", action="append", dest="symbols", default=[])
    parser.add_argument("--symbol-map", action="append", default=[], metavar="CANONICAL=BROKER")
    parser.add_argument("--news-json", default=None)
    parser.add_argument("--cost-policy", default=None)
    parser.add_argument("--output", default="runtime/demo_preflight_report.json")
    parser.add_argument("--require-paper-ready", action="store_true")
    args = parser.parse_args()

    profile = default_m15_first_profile()
    symbols = args.symbols or list(profile.watchlist)
    symbol_map = _parse_symbol_map(args.symbol_map)
    settings = MT5ConnectionSettings(
        login=args.login,
        password=args.password,
        server=args.server,
        terminal_path=args.terminal_path,
        symbol_map=symbol_map,
    )
    feed = MT5MarketDataFeed({args.account_id: settings})
    account = AccountConfig(account_id=args.account_id, enabled=True, risk_pct=profile.risk_per_trade_pct, target_r=2.0, broker="MT5_DEMO")
    try:
        report = MT5DemoValidator(feed).validate(
            account,
            symbols,
            expected_login=args.login,
            news_json=args.news_json,
            cost_policy_json=args.cost_policy,
        )
        payload = report.to_dict()
        payload["profile"] = profile.name
        payload["watchlist"] = list(profile.watchlist)
        payload["symbol_map"] = symbol_map
        payload["mode"] = "READ_ONLY_PREFLIGHT"
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        if args.require_paper_ready:
            return 0 if report.ready_for_paper_supervision else 3
        return 0 if report.ready_for_observation else 2
    finally:
        feed.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
