from __future__ import annotations
import argparse
from atlas.services.h4_human_approval import H4HumanApprovalStore

p=argparse.ArgumentParser(description="Set/revoke Atlas H4 human approval (local; zero API calls).")
p.add_argument("symbol")
p.add_argument("trend", nargs="?", choices=["BULLISH","BEARISH","RANGE","TRANSITION"])
p.add_argument("--start", type=float)
p.add_argument("--end", type=float)
p.add_argument("--note", default="")
p.add_argument("--revoke", action="store_true")
a=p.parse_args()
s=H4HumanApprovalStore()
if a.revoke:
    s.revoke(a.symbol); print(f"REVOKED {a.symbol.upper()}")
else:
    if not a.trend: p.error("trend is required unless --revoke is used")
    x=s.approve(a.symbol,a.trend,a.start,a.end,a.note)
    print(f"APPROVED {x.symbol}: {x.trend} | impulse={x.impulse_start} -> {x.impulse_end} | {x.approved_at_utc}")
