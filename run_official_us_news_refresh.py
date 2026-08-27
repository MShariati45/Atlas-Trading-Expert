"""Fetch the official U.S. BLS release calendar into an Atlas partial news bundle.

This is intentionally marked PARTIAL coverage (USD only). It is useful for validating
Atlas's official-source ingestion but is NOT sufficient for paper-supervision readiness,
which requires USD/EUR/CAD/JPY coverage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

from atlas.services.official_calendar import parse_bls_ics

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=BLS_ICS)
    p.add_argument("--output", default="runtime/news_bls_usd.json")
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--horizon-days", type=int, default=120)
    args = p.parse_args()

    req = Request(args.url, headers={"User-Agent": "AtlasTradingExpert/0.24.2", "Accept": "text/calendar,*/*"})
    with urlopen(req, timeout=args.timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=args.horizon_days)
    events = [e for e in parse_bls_ics(text, source_url=args.url) if now - timedelta(hours=1) <= e.starts_at_utc <= horizon]
    payload = {
        "generated_at_utc": now.isoformat(),
        "valid_until_utc": (now + timedelta(hours=24)).isoformat(),
        "source_name": "U.S. Bureau of Labor Statistics official release calendar",
        "source_url": args.url,
        "coverage_currencies": ["USD"],
        "coverage_status": "PARTIAL_NOT_PAPER_READY",
        "events": [e.to_payload() for e in events],
        "notes": [
            "Official BLS schedule covers USD releases only.",
            "Atlas paper supervision still requires trusted EUR, CAD, and JPY coverage.",
        ],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    high = sum(1 for e in events if e.impact == "HIGH")
    print(json.dumps({"status": "PARTIAL_OK", "output": str(out), "events": len(events), "high_impact": high, "coverage": ["USD"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
