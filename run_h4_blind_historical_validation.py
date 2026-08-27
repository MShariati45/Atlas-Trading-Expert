from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.research.structure_v2 import analyze_structure

MODEL = "STRUCTURE_V2_6_H4_BLIND_HISTORICAL_VALIDATION_v0.24.12.2"


def _bar_dict(bar: Any) -> dict[str, Any]:
    t = getattr(bar, "time_utc", getattr(bar, "time", None))
    return {
        "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
    }


def choose_blind_cutoffs(n: int, *, cases: int = 5, min_history: int = 650, holdout_bars: int = 180) -> list[int]:
    """Return deterministic, well-spaced historical cutoffs.

    Each cutoff is an exclusive slice endpoint. The newest holdout is excluded so
    the four current teaching examples cannot be reused as blind cases.
    """
    upper = n - holdout_bars
    if upper <= min_history:
        return []
    if cases <= 1:
        return [upper]
    span = upper - min_history
    points = [min_history + round(span * i / (cases - 1)) for i in range(cases)]
    # De-duplicate while preserving order.
    out: list[int] = []
    for p in points:
        p = min(max(p, min_history), upper)
        if not out or p != out[-1]:
            out.append(p)
    return out


def _write_rows(sample: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close"])
        w.writeheader()
        w.writerows(sample)


def _write_full_context(rows: list[dict[str, Any]], path: Path, cutoff: int) -> None:
    """Export exactly the causal prefix that Atlas analyzed for this blind case."""
    _write_rows(rows[:cutoff], path)


def _write_window(rows: list[dict[str, Any]], path: Path, cutoff: int, before: int = 180, after: int = 0) -> None:
    """Export a compact recent window for quick chart review; never used by the detector."""
    lo = max(0, cutoff - before)
    hi = min(len(rows), cutoff + after)
    _write_rows(rows[lo:hi], path)


def _snapshot(symbol: str, rows: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    # Feed ONLY bars available at the historical cutoff. This is the anti-lookahead rule.
    prefix = rows[:cutoff]
    result = analyze_structure(prefix, symbol=symbol, timeframe="H4")
    return {
        "symbol": symbol,
        "cutoff_index_exclusive": cutoff,
        "cutoff_time": prefix[-1]["time"],
        "bars_available": len(prefix),
        "dominant_trend": result.dominant_trend,
        "regime": result.regime,
        "transition_state": result.transition_state,
        "origin_time": result.impulse_origin.time if result.impulse_origin else None,
        "origin": result.impulse_origin.price if result.impulse_origin else None,
        "endpoint_time": result.impulse_endpoint.time if result.impulse_endpoint else None,
        "endpoint": result.impulse_endpoint.price if result.impulse_endpoint else None,
        "control_time": result.control_pivot.time if result.control_pivot else None,
        "control": result.control_pivot.price if result.control_pivot else None,
        "strategic_pivot_count": len(result.strategic_pivots),
        "trendline_anchor_count": result.trendline_anchor_count,
        "current_correction": asdict(result.current_correction) if result.current_correction else None,
        "anti_lookahead_ok": True,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Atlas v0.24.12.2 read-only blind historical H4 validation with full causal context export")
    p.add_argument("--symbols", default="EURUSD,USDJPY,USDCAD,XAUUSD")
    p.add_argument("--bars", type=int, default=2200, help="H4 bars to collect per symbol")
    p.add_argument("--cases", type=int, default=5, help="Blind historical cutoffs per symbol")
    p.add_argument("--holdout-bars", type=int, default=180, help="Exclude newest bars used in current teaching")
    p.add_argument("--account-id", default="DEMO")
    p.add_argument("--terminal-path", default=None)
    p.add_argument("--login", type=int, default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--server", default=None)
    p.add_argument("--output", default="runtime/h4_blind_historical_validation.json")
    args = p.parse_args()

    settings = MT5ConnectionSettings(
        terminal_path=args.terminal_path,
        login=args.login,
        password=args.password,
        server=args.server,
    )
    feed = MT5MarketDataFeed({args.account_id: settings})
    account = AccountConfig(account_id=args.account_id, broker="MT5", enabled=True, risk_pct=0.0, target_r=2.0)
    feed.connect(account)

    report: dict[str, Any] = {
        "mode": "READ_ONLY_BLIND_HISTORICAL_VALIDATION",
        "execution": "LOCKED",
        "model": MODEL,
        "method": {
            "timeframe": "H4",
            "direction": "historical cutoff -> no future bars -> backward strategic reconstruction",
            "teaching_answers_used": False,
            "current_teaching_holdout_bars": args.holdout_bars,
            "cases_per_symbol_requested": args.cases,
            "manual_review_required": True,
            "purpose": "test generalization before freezing H4 and before teaching H1",
        },
        "symbols": {},
    }

    summary_rows: list[dict[str, Any]] = []
    try:
        for symbol in [x.strip().upper() for x in args.symbols.split(",") if x.strip()]:
            bars = feed.closed_bars(symbol, "H4", args.bars)
            rows = [_bar_dict(b) for b in bars]
            cutoffs = choose_blind_cutoffs(len(rows), cases=args.cases, holdout_bars=args.holdout_bars)
            symbol_report = {
                "bars_collected": len(rows),
                "first_bar": rows[0]["time"] if rows else None,
                "last_bar": rows[-1]["time"] if rows else None,
                "blind_cases": [],
            }
            print(f"\n{symbol} H4: collected {len(rows)} bars; blind cases={len(cutoffs)}")
            for i, cutoff in enumerate(cutoffs, start=1):
                snap = _snapshot(symbol, rows, cutoff)
                case_id = f"{symbol}_H4_BLIND_{i:02d}"
                snap["case_id"] = case_id
                full_path = Path(f"runtime/h4_blind_cases/{case_id}.csv")
                window_path = Path(f"runtime/h4_blind_cases/{case_id}_window180.csv")
                _write_full_context(rows, full_path, cutoff)
                _write_window(rows, window_path, cutoff, before=180, after=0)
                snap["analysis_context_csv"] = str(full_path)
                snap["analysis_context_bars"] = cutoff
                snap["chart_window_csv"] = str(window_path)
                symbol_report["blind_cases"].append(snap)
                summary_rows.append({
                    "case_id": case_id,
                    "symbol": symbol,
                    "cutoff_time": snap["cutoff_time"],
                    "trend": snap["dominant_trend"],
                    "regime": snap["regime"],
                    "transition": snap["transition_state"],
                    "origin_time": snap["origin_time"],
                    "origin": snap["origin"],
                    "endpoint_time": snap["endpoint_time"],
                    "endpoint": snap["endpoint"],
                    "control": snap["control"],
                    "anti_lookahead_ok": snap["anti_lookahead_ok"],
                })
                print(
                    f"  {case_id} cutoff={snap['cutoff_time'][:10]} "
                    f"trend={snap['dominant_trend']} regime={snap['regime']} "
                    f"impulse={snap['origin']} -> {snap['endpoint']}"
                )
            report["symbols"][symbol] = symbol_report
    finally:
        feed.shutdown()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary_path = Path("runtime/h4_blind_historical_summary.csv")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "case_id", "symbol", "cutoff_time", "trend", "regime", "transition",
            "origin_time", "origin", "endpoint_time", "endpoint", "control", "anti_lookahead_ok",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summary_rows)

    print("\nBLIND H4 HISTORICAL VALIDATION SET CREATED")
    print(f"Cases: {len(summary_rows)} (no teaching answers embedded)")
    print(f"Report: {out}")
    print(f"Summary: {summary_path}")
    print("Full causal case context: runtime\\h4_blind_cases\\<case_id>.csv")
    print("Compact review windows: runtime\\h4_blind_cases\\<case_id>_window180.csv")
    print("Next step: manually review the full blind H4 context before freezing H4.")


if __name__ == "__main__":
    main()
