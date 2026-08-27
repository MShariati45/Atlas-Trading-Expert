from __future__ import annotations
import argparse, json
from dataclasses import asdict
from atlas.backtest.dataset import audit_dataset

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("dataset", nargs="?", default="historical_data/one_year")
    args=ap.parse_args()
    audit=audit_dataset(args.dataset)
    print(json.dumps(asdict(audit), indent=2))
    return 0 if audit.ready else 2
if __name__=="__main__": raise SystemExit(main())
