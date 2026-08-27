"""Atlas v0.24.14 read-only M15 candlestick reversal challenger.

Purpose
-------
Research whether a small set of objective 1/2/3-candle M15 reversal patterns adds value
when aligned with a simple H4 dominant direction and nearby D1/H4/H1 support/resistance.

This runner NEVER sends orders and does not modify the shadow-paper supervisor state.
"""
from __future__ import annotations

import argparse
import csv
import json
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import Candle, MT5MarketDataFeed
from atlas.research.candlestick_challenger import (
    RecentImpulseDirectionEngine,
    RollingZoneEngine,
    atr,
    build_trade_candidate,
    detect_patterns,
    evaluate_outcome,
    find_choch_confirmation,
)

SYMBOLS = ["EURUSD", "USDJPY", "USDCAD", "XAUUSD"]
TIMEFRAMES = ["D1", "H4", "H1", "M15"]
TARGETS = [2.0, 3.0, 4.0]
VANCOUVER = ZoneInfo("America/Vancouver")


def parse_map(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"Invalid --symbol-map {raw!r}; use CANONICAL=BROKER")
        a, b = (x.strip() for x in raw.split("=", 1))
        out[a.upper()] = b
    return out


def _write_bars(path: Path, bars: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "open", "high", "low", "close", "tick_volume", "spread_points", "real_volume"])
        for b in bars:
            w.writerow([b.time_utc.isoformat(), b.open, b.high, b.low, b.close, b.tick_volume, b.spread_points, b.real_volume])


def _prefix(bars: list[Candle], times: list[datetime], cutoff: datetime) -> list[Candle]:
    return bars[:bisect_right(times, cutoff)]


def _max_streak(values: list[str], desired: str) -> int:
    best = cur = 0
    for v in values:
        if v == desired:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize(rows: list[dict], keys: list[str]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in keys)].append(r)
    out: list[dict] = []
    for group_key, items in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        resolved = [x for x in items if x["outcome"] in {"WIN", "LOSS"}]
        wins = sum(x["outcome"] == "WIN" for x in resolved)
        losses = sum(x["outcome"] == "LOSS" for x in resolved)
        n = len(resolved)
        r_values = [float(x["realized_r"]) for x in resolved if x["realized_r"] not in {None, ""}]
        sequence = [x["outcome"] for x in sorted(resolved, key=lambda z: z["entry_time"])]
        row = {k: v for k, v in zip(keys, group_key)}
        row.update({
            "signals": len(items),
            "resolved": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(100.0 * wins / n, 2) if n else None,
            "expectancy_r": round(mean(r_values), 4) if r_values else None,
            "net_r": round(sum(r_values), 2) if r_values else 0.0,
            "max_consecutive_wins": _max_streak(sequence, "WIN"),
            "max_consecutive_losses": _max_streak(sequence, "LOSS"),
            "avg_mfe_r": round(mean(float(x["mfe_r"]) for x in resolved), 3) if resolved else None,
            "avg_mae_r": round(mean(float(x["mae_r"]) for x in resolved), 3) if resolved else None,
        })
        out.append(row)
    return out


def portfolio_gate(rows: list[dict]) -> list[dict]:
    """Apply Atlas two-bullet rule to a signal stream for each configuration/target."""
    selected: list[dict] = []
    group_keys = sorted({(r["filter_name"], r["entry_model"], r["target_r"]) for r in rows})
    for cfg in group_keys:
        group = [r for r in rows if (r["filter_name"], r["entry_model"], r["target_r"]) == cfg]
        by_day: dict[str, list[dict]] = defaultdict(list)
        for r in group:
            local_day = datetime.fromisoformat(r["entry_time"]).astimezone(VANCOUVER).date().isoformat()
            by_day[local_day].append(r)
        for day, items in by_day.items():
            used_symbols: set[str] = set()
            bullets = 0
            for r in sorted(items, key=lambda x: (-float(x["quality"]), x["entry_time"])):
                if bullets >= 2 or r["symbol"] in used_symbols:
                    continue
                selected.append({**r, "vancouver_day": day})
                used_symbols.add(r["symbol"])
                bullets += 1
    return selected


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only Atlas M15 candlestick reversal challenger")
    p.add_argument("--account-id", default="DEMO")
    p.add_argument("--terminal-path", default=None)
    p.add_argument("--login", type=int, default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--server", default=None)
    p.add_argument("--symbol-map", action="append", default=[])
    p.add_argument("--days", type=int, default=366)
    p.add_argument("--out", default="runtime/candlestick_sr_independent")
    args = p.parse_args()

    if args.days < 120:
        raise SystemExit("--days must be at least 120")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    settings = MT5ConnectionSettings(
        login=args.login, password=args.password, server=args.server,
        terminal_path=args.terminal_path, symbol_map=parse_map(args.symbol_map),
    )
    feed = MT5MarketDataFeed({args.account_id: settings})
    acct = AccountConfig(args.account_id, True, 0.5)

    # Keep the end behind the forming M15 candle.
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % 15)
    end -= timedelta(minutes=15)
    start = end - timedelta(days=args.days)
    warmup_start = start - timedelta(days=380)

    all_rows: list[dict] = []
    raw_signal_count = 0
    direction_engine = RecentImpulseDirectionEngine()
    zone_engine = RollingZoneEngine()

    try:
        feed.connect(acct)
        account_snapshot = feed.account_snapshot()
        print("=" * 78)
        print("ATLAS v0.24.15 - M15 CANDLESTICK S/R INDEPENDENT CHALLENGER")
        print("READ ONLY: no orders, no shadow-state modification")
        print(f"Window: {start.isoformat()} -> {end.isoformat()}")
        print("Patterns: Hammer/Pin, Shooting Star/Pin, Bull/Bear Engulfing, Morning/Evening Star\nPrimary filter: D1/H4/H1 S/R only; NO H4 directional alignment")
        print("Targets: 2R, 3R, 4R | Entry models: EARLY and CHOCH-CONFIRMED")
        print("=" * 78)

        for symbol in SYMBOLS:
            meta = feed.ensure_symbol(symbol)
            data: dict[str, list[Candle]] = {}
            times: dict[str, list[datetime]] = {}
            print(f"\n[{symbol}] collecting broker-native history...")
            for tf in TIMEFRAMES:
                bars = feed.bars_range(symbol, tf, warmup_start, end)
                data[tf] = bars
                times[tf] = [b.time_utc for b in bars]
                _write_bars(out / "bars" / f"{symbol}_{tf}.csv", bars)
                print(f"  {tf}: {len(bars)} bars")
            m15 = data["M15"]
            if len(m15) < 500:
                print(f"  SKIP: insufficient M15 history")
                continue

            last_key: dict[tuple[str, str], int] = {}
            symbol_candidates = 0
            for i in range(25, len(m15) - 170):
                b = m15[i]
                if b.time_utc < start or b.time_utc > end:
                    continue
                current_atr = atr(m15[: i + 1], 20)
                if current_atr <= 0:
                    continue
                patterns = detect_patterns(m15, i, current_atr)
                if not patterns:
                    continue
                for sig in patterns:
                    # Basic dedupe: same pattern/direction cannot fire repeatedly inside 4 M15 bars.
                    dedupe_key = (sig.pattern, sig.direction)
                    if i - last_key.get(dedupe_key, -999) <= 4:
                        continue
                    last_key[dedupe_key] = i
                    raw_signal_count += 1

                    cutoff = sig.end_time
                    cutoff_dt = datetime.fromisoformat(cutoff)
                    h4_hist = _prefix(data["H4"], times["H4"], cutoff_dt)
                    # H4 is recorded for audit/comparison only. It is NOT an eligibility gate.
                    direction = direction_engine.classify(h4_hist)
                    histories = {
                        tf: _prefix(data[tf], times[tf], cutoff_dt)
                        for tf in ("D1", "H4", "H1")
                    }
                    zone = zone_engine.nearest_hit(sig.direction, sig.pattern_low, sig.pattern_high, current_atr, histories)
                    if zone is None or zone.strength < 0.45:
                        continue

                    # Early model, with both broad and counter-move-filter variants.
                    early = build_trade_candidate(symbol, m15, sig, direction, zone, meta.point, "EARLY")
                    if early:
                        variants = ["ZONE_PATTERN"]
                        if early.counter_move:
                            variants.append("ZONE_PATTERN_COUNTERMOVE")
                        for variant in variants:
                            early.filter_name = variant
                            entry_idx = sig.end_index
                            for target_r in TARGETS:
                                outcome = evaluate_outcome(m15, entry_idx, early, target_r)
                                all_rows.append({
                                    **early.to_dict(), "quality": sig.quality,
                                    "target_r": target_r, **outcome.to_dict(),
                                })
                            symbol_candidates += 1

                    # Confirmed model: first M15 CHOCH inside four bars.
                    confirm_idx = find_choch_confirmation(m15, sig, max_wait_bars=4, internal_lookback=5)
                    if confirm_idx is not None:
                        confirmed = build_trade_candidate(
                            symbol, m15, sig, direction, zone, meta.point, "CONFIRMED",
                            confirmation_index=confirm_idx, filter_name="ZONE_PATTERN_CHOCH",
                        )
                        if confirmed:
                            variants = ["ZONE_PATTERN_CHOCH"]
                            if confirmed.counter_move:
                                variants.append("ZONE_PATTERN_COUNTERMOVE_CHOCH")
                            for variant in variants:
                                confirmed.filter_name = variant
                                for target_r in TARGETS:
                                    outcome = evaluate_outcome(m15, confirm_idx, confirmed, target_r)
                                    all_rows.append({
                                        **confirmed.to_dict(), "quality": sig.quality,
                                        "target_r": target_r, **outcome.to_dict(),
                                    })
                            symbol_candidates += 1
            print(f"  eligible candidate entries: {symbol_candidates}")
    finally:
        feed.shutdown()

    # Detailed events.
    events_csv = out / "candlestick_trade_events.csv"
    if all_rows:
        with events_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            w.writeheader(); w.writerows(all_rows)
    else:
        events_csv.write_text("", encoding="utf-8")

    summary_keys = ["filter_name", "entry_model", "target_r", "symbol", "pattern", "zone_timeframe"]
    summary_rows = summarize(all_rows, summary_keys)
    summary_csv = out / "candlestick_summary.csv"
    if summary_rows:
        with summary_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            w.writeheader(); w.writerows(summary_rows)
    else:
        summary_csv.write_text("", encoding="utf-8")

    # Overall configuration summary and Atlas daily 2-bullet simulation.
    overall = summarize(all_rows, ["filter_name", "entry_model", "target_r"])
    gated_rows = portfolio_gate(all_rows)
    gated = summarize(gated_rows, ["filter_name", "entry_model", "target_r"])

    payload = {
        "atlas_version": "0.24.14",
        "mode": "READ_ONLY_M15_CANDLESTICK_REVERSAL_CHALLENGER",
        "window": {"start_utc": start.isoformat(), "end_utc": end.isoformat()},
        "symbols": SYMBOLS,
        "raw_pattern_events": raw_signal_count,
        "qualified_outcome_rows": len(all_rows),
        "account_login": int(account_snapshot.login),
        "broker_server": account_snapshot.server,
        "patterns": ["HAMMER_PIN", "SHOOTING_STAR_PIN", "BULLISH_ENGULFING", "BEARISH_ENGULFING", "MORNING_STAR", "EVENING_STAR"],
        "alignment": "H4 recent-impulse direction + D1/H4/H1 major reaction zone; H1 direction is not required",
        "entry_models": {
            "EARLY": "pattern close",
            "CONFIRMED": "first M15 close through recent internal S/R within 4 bars",
        },
        "targets_r": TARGETS,
        "stop_policy": "beyond entire pattern/recent M15 structural invalidation plus max(1.5x spread, 0.10 ATR, 3 points)",
        "same_bar_policy": "conservative: if target and stop are both touched in one M15 bar, count LOSS",
        "overall": overall,
        "portfolio_two_bullet": gated,
        "important": [
            "Research/challenger only: this does not enable the candlestick agent in demo execution.",
            "No lookahead is used for H4 direction or D1/H4/H1 zones; only bars at or before the signal cutoff are used.",
            "H1 is used only as a support/resistance timeframe, not as a directional alignment gate.",
            "Do not promote configurations from tiny samples. Prefer adequate trade count, positive expectancy and stable symbol/pattern behavior.",
        ],
    }
    json_path = out / "candlestick_challenger_report.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = [
        "# Atlas v0.24.14 - M15 Candlestick Reversal Challenger", "",
        "Read-only one-year research. No orders are sent and the shadow supervisor is not modified.", "",
        "## Overall configurations", "",
        "| Filter | Entry | Target | Resolved | Win % | Expectancy R | Net R | Max W | Max L |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in overall:
        md.append(f"| {r['filter_name']} | {r['entry_model']} | {r['target_r']}R | {r['resolved']} | {r['win_rate_pct']} | {r['expectancy_r']} | {r['net_r']} | {r['max_consecutive_wins']} | {r['max_consecutive_losses']} |")
    md += ["", "## Two-bullet daily portfolio gate", "", "Maximum two trades per Vancouver trading day, maximum one per symbol; highest pattern quality is selected first.", "", "| Filter | Entry | Target | Resolved | Win % | Expectancy R | Net R | Max W | Max L |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in gated:
        md.append(f"| {r['filter_name']} | {r['entry_model']} | {r['target_r']}R | {r['resolved']} | {r['win_rate_pct']} | {r['expectancy_r']} | {r['net_r']} | {r['max_consecutive_wins']} | {r['max_consecutive_losses']} |")
    md += ["", "## Files", "", "- `candlestick_trade_events.csv`: every candidate/target outcome", "- `candlestick_summary.csv`: symbol/pattern/zone-timeframe breakdown", "- `candlestick_challenger_report.json`: machine-readable summary", "- `bars/`: broker-native D1/H4/H1/M15 inputs used for audit", ""]
    (out / "REPORT.md").write_text("\n".join(md), encoding="utf-8")

    print("\n" + "=" * 78)
    print("CANDLESTICK CHALLENGER COMPLETE")
    print(f"Raw pattern events: {raw_signal_count}")
    print(f"Qualified outcome rows: {len(all_rows)}")
    print(f"Report: {out / 'REPORT.md'}")
    print(f"Summary: {summary_csv}")
    print(f"Events: {events_csv}")
    print("No orders were sent.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
