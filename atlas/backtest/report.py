
import csv, json
from pathlib import Path
from .engine import summarize

def write_reports(trades, out_dir):
    out=Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rows=[t.to_dict() for t in trades]
    if rows:
        with (out/"trades.csv").open("w", newline="", encoding="utf-8") as f:
            w=csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    summary=summarize(trades)
    (out/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
