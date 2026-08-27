
"""Atlas v0.17 historical paper harness.

This runner intentionally requires candidate inputs produced by the normal Atlas
pipeline. It does not fabricate signals from OHLC. Live MT5 history collection
must be run on the user's machine/VPS with MT5 connected.
"""
import argparse, csv, json
from pathlib import Path
from atlas.backtest.models import PaperTrade
from atlas.backtest.engine import HistoricalPaperHarness
from atlas.backtest.report import write_reports

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, help="JSONL Atlas approved paper candidates")
    ap.add_argument("--bars-dir", required=True, help="Directory containing SYMBOL_M15.csv future bars")
    ap.add_argument("--out", default="backtest_output")
    args=ap.parse_args()
    engine=HistoricalPaperHarness()
    trades=[]
    for line in Path(args.candidates).read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        obj=json.loads(line); bars=[]
        f=Path(args.bars_dir)/f"{obj['symbol']}_M15.csv"
        if f.exists():
            with f.open(encoding="utf-8") as h:
                allbars=list(csv.DictReader(h))
            bars=[b for b in allbars if str(b.get("time","")) > str(obj["signal_time"])]
        t=PaperTrade(**obj); trades.append(engine.resolve(t,bars))
    print(json.dumps(write_reports(trades,args.out), indent=2))
if __name__=="__main__": main()
