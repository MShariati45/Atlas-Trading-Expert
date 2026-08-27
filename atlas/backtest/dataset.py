from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv
import json
from datetime import datetime

REQUIRED_TFS = {"D1", "H4", "H1", "M15"}

@dataclass(slots=True)
class DatasetIssue:
    severity: str
    code: str
    symbol: str = ""
    timeframe: str = ""
    detail: str = ""

@dataclass(slots=True)
class DatasetAudit:
    ready: bool
    issues: list[dict]
    bars_by_symbol: dict[str, dict[str, int]]


def audit_dataset(root: str | Path, min_m15_rows: int = 10000) -> DatasetAudit:
    root = Path(root)
    manifest_file = root / "manifest.json"
    issues: list[DatasetIssue] = []
    counts: dict[str, dict[str, int]] = {}
    if not manifest_file.exists():
        return DatasetAudit(False, [asdict(DatasetIssue("ERROR", "MANIFEST_MISSING"))], {})
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    records = manifest.get("records", [])
    for r in records:
        s, tf, n = r["symbol"], r["timeframe"], int(r["rows"])
        counts.setdefault(s, {})[tf] = n
        f = root / r["file"]
        if not f.exists():
            issues.append(DatasetIssue("ERROR", "BAR_FILE_MISSING", s, tf, str(f)))
            continue
        with f.open(encoding="utf-8") as h:
            rows = list(csv.DictReader(h))
        if len(rows) != n:
            issues.append(DatasetIssue("ERROR", "ROW_COUNT_MISMATCH", s, tf, f"manifest={n},file={len(rows)}"))
        times = [datetime.fromisoformat(x["time_utc"]) for x in rows]
        if any(b <= a for a, b in zip(times, times[1:])):
            issues.append(DatasetIssue("ERROR", "NON_MONOTONIC_OR_DUPLICATE_TIME", s, tf))
        for x in rows:
            o,h,l,c = map(float, (x["open"],x["high"],x["low"],x["close"]))
            if h < max(o,c,l) or l > min(o,c,h):
                issues.append(DatasetIssue("ERROR", "INVALID_OHLC", s, tf, x["time_utc"]))
                break
    for s, tfs in counts.items():
        missing = REQUIRED_TFS - set(tfs)
        for tf in sorted(missing):
            issues.append(DatasetIssue("ERROR", "TIMEFRAME_MISSING", s, tf))
        if tfs.get("M15", 0) < min_m15_rows:
            issues.append(DatasetIssue("WARNING", "SHORT_M15_HISTORY", s, "M15", str(tfs.get("M15",0))))
    ready = not any(i.severity == "ERROR" for i in issues)
    return DatasetAudit(ready, [asdict(i) for i in issues], counts)
