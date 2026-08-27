from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import csv, json

@dataclass(frozen=True, slots=True)
class SymbolCalibrationGate:
    symbol: str
    samples: int
    positive_samples: int
    stale_samples: int
    p95_spread_points: float | None
    current_limit_points: float | None
    passed: bool
    reasons: tuple[str, ...]
    def to_dict(self): return asdict(self)

def _pct(values, q):
    if not values: return None
    xs=sorted(values); pos=(len(xs)-1)*q; lo=int(pos); hi=min(lo+1,len(xs)-1); f=pos-lo
    return xs[lo]*(1-f)+xs[hi]*f

def audit_calibration(csv_path: str|Path, policy_path: str|Path, *, min_samples: int=120, max_tick_age_seconds: float=30.0):
    policy=json.loads(Path(policy_path).read_text(encoding='utf-8'))
    by={s: [] for s in policy.get('symbols', {})}
    stale={s:0 for s in by}
    with Path(csv_path).open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            s=r.get('symbol','').upper()
            if s not in by: continue
            try: sp=float(r['spread_points']); age=float(r['tick_age_seconds'])
            except Exception: continue
            by[s].append(sp)
            if age > max_tick_age_seconds: stale[s]+=1
    out={}
    for s, vals in by.items():
        reasons=[]; positive=[v for v in vals if v>0]; p95=_pct(positive,.95)
        limit=float(policy['symbols'][s]['max_spread_points'])
        if len(vals)<min_samples: reasons.append('INSUFFICIENT_SAMPLES')
        if len(positive)<min_samples: reasons.append('INSUFFICIENT_POSITIVE_SPREAD_SAMPLES')
        if stale[s]>0: reasons.append('STALE_TICK_SAMPLES_PRESENT')
        if p95 is None: reasons.append('P95_UNAVAILABLE')
        elif p95>limit: reasons.append('OBSERVED_P95_EXCEEDS_CURRENT_POLICY_LIMIT')
        out[s]=SymbolCalibrationGate(s,len(vals),len(positive),stale[s],p95,limit,not reasons,tuple(reasons))
    passed=bool(out) and all(x.passed for x in out.values())
    return {'mode':'READ_ONLY_BROKER_CALIBRATION_AUDIT','passed':passed,'symbols':{s:x.to_dict() for s,x in out.items()},
            'important':['No orders were sent.','This audit never changes broker-cost limits automatically.','Demo fill slippage remains a separate execution-phase measurement.']}
