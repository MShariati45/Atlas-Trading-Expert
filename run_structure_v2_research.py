from __future__ import annotations
import argparse, csv, json
from datetime import datetime
from pathlib import Path
from atlas.execution.models import AccountConfig
from atlas.execution.mt5_bridge import MT5ConnectionSettings
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.research.structure_v2 import analyze_structure


def _bar_dict(bar):
    t = getattr(bar, "time_utc", getattr(bar, "time", None))
    return {
        "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
        "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close": float(bar.close),
    }


def _write_teaching_window(bars, path: Path, rows_n: int = 180):
    rows = [_bar_dict(b) for b in bars][-rows_n:]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close"])
        w.writeheader(); w.writerows(rows)


def _date_distance_days(ts: str, target: str) -> int | None:
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        t = datetime.fromisoformat(target + "T00:00:00+00:00").date()
        return abs((d - t).days)
    except Exception:
        return None


def _benchmark(result, *, trend, origin, endpoint, origin_tol, endpoint_tol, regimes=None, origin_date=None, date_tol_days=3):
    o = result.impulse_origin.price if result.impulse_origin else None
    e = result.impulse_endpoint.price if result.impulse_endpoint else None
    trend_ok = result.dominant_trend == trend
    origin_ok = o is not None and abs(o-origin) <= origin_tol
    endpoint_ok = e is not None and abs(e-endpoint) <= endpoint_tol
    regime_ok = True if not regimes else result.regime in set(regimes)
    date_gap = _date_distance_days(result.impulse_origin.time, origin_date) if origin_date and result.impulse_origin else None
    date_ok = True if origin_date is None else (date_gap is not None and date_gap <= date_tol_days)
    status = "PASS" if all((trend_ok, origin_ok, endpoint_ok, regime_ok, date_ok)) else "REVIEW"
    return {
        "expected_trend": trend,
        "expected_origin_approx": origin,
        "expected_endpoint_approx": endpoint,
        "expected_regime_any_of": regimes,
        "expected_origin_date_approx": origin_date,
        "observed_trend": result.dominant_trend,
        "observed_regime": result.regime,
        "observed_transition": result.transition_state,
        "observed_origin_time": result.impulse_origin.time if result.impulse_origin else None,
        "observed_origin": o,
        "observed_endpoint": e,
        "trend_ok": trend_ok,
        "origin_ok": origin_ok,
        "endpoint_ok": endpoint_ok,
        "regime_ok": regime_ok,
        "origin_date_gap_days": date_gap,
        "origin_date_ok": date_ok,
        "status": status,
    }


def main():
    p=argparse.ArgumentParser(description="Atlas v0.24.11 H4 backward strategic reconstruction read-only teaching runner")
    p.add_argument("--symbols", default="EURUSD,USDJPY,USDCAD,XAUUSD")
    p.add_argument("--timeframes", default="H4,H1,M15")
    p.add_argument("--bars", type=int, default=900)
    p.add_argument("--account-id", default="DEMO")
    p.add_argument("--terminal-path", default=None)
    p.add_argument("--login", type=int, default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--server", default=None)
    p.add_argument("--output", default="runtime/structure_v2_research.json")
    args=p.parse_args()
    settings=MT5ConnectionSettings(terminal_path=args.terminal_path,login=args.login,password=args.password,server=args.server)
    feed=MT5MarketDataFeed({args.account_id:settings})
    account=AccountConfig(account_id=args.account_id,broker="MT5",enabled=True,risk_pct=0.0,target_r=2.0)
    feed.connect(account)
    report={"mode":"READ_ONLY_RESEARCH","execution":"LOCKED","model":"STRUCTURE_V2_5_H4_BACKWARD_STRATEGIC_RECONSTRUCTION_v0.24.11","results":{},"benchmarks":{}}
    try:
        symbols=[x.strip().upper() for x in args.symbols.split(",") if x.strip()]
        tfs=[x.strip().upper() for x in args.timeframes.split(",") if x.strip()]
        h4_cache={}
        for sym in symbols:
            report["results"][sym]={}
            for tf in tfs:
                bars=feed.closed_bars(sym,tf,args.bars)
                r=analyze_structure(bars,symbol=sym,timeframe=tf)
                report["results"][sym][tf]=r.to_dict()
                o=r.impulse_origin.price if r.impulse_origin else None
                e=r.impulse_endpoint.price if r.impulse_endpoint else None
                print(f"{sym:7s} {tf:4s} trend={r.dominant_trend:8s} regime={r.regime:10s} impulse={o} -> {e} transition={r.transition_state}")
                if tf=="H4":
                    h4_cache[sym]=(r,bars)
                    _write_teaching_window(bars, Path(f"runtime/{sym.lower()}_h4_teaching_window.csv"))

        specs={
            "XAUUSD": dict(trend="BULLISH", origin=4310.66, endpoint=4630.0, origin_tol=20.0, endpoint_tol=35.0, regimes=["IMPULSE"], origin_date="2026-08-14"),
            "EURUSD": dict(trend="BULLISH", origin=1.15124, endpoint=1.17108, origin_tol=0.0020, endpoint_tol=0.0015, regimes=["IMPULSE","CORRECTION","RANGE"]),
            "USDJPY": dict(trend="BEARISH", origin=160.388, endpoint=155.235, origin_tol=0.60, endpoint_tol=0.45, regimes=["CORRECTION","RANGE"]),
            "USDCAD": dict(trend="BEARISH", origin=1.41273, endpoint=1.37312, origin_tol=0.0030, endpoint_tol=0.0020, regimes=["IMPULSE"]),
        }
        for sym,spec in specs.items():
            if sym not in h4_cache:
                continue
            r,_=h4_cache[sym]
            b=_benchmark(r, **spec)
            report["benchmarks"][f"{sym}_H4_TEACHING_CASE"] = b
            print(f"  teaching benchmark {sym} H4: {b['status']}  expected {spec['origin']} -> {spec['endpoint']}")

        passed=sum(1 for b in report["benchmarks"].values() if b["status"]=="PASS")
        total=len(report["benchmarks"])
        report["h4_teaching_summary"]={"passed":passed,"total":total,"all_pass": total>0 and passed==total}
        print(f"\nH4 teaching summary: {passed}/{total} PASS")
    finally:
        feed.shutdown()
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(f"Saved: {path}")
    print("H4 diagnostic CSVs: runtime\\<symbol>_h4_teaching_window.csv")

if __name__=="__main__": main()
