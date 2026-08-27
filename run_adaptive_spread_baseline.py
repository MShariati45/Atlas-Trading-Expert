import argparse, json
from pathlib import Path
from atlas.services.adaptive_spread_guard import build_baseline_from_csv

p=argparse.ArgumentParser()
p.add_argument('--csv', default='runtime/broker_spread_samples.csv')
p.add_argument('--out', default='runtime/adaptive_spread_baseline.json')
p.add_argument('--min-session-samples', type=int, default=60)
p.add_argument('--min-all-samples', type=int, default=120)
a=p.parse_args()
result=build_baseline_from_csv(a.csv,min_session_samples=a.min_session_samples,min_all_samples=a.min_all_samples)
Path(a.out).parent.mkdir(parents=True,exist_ok=True)
Path(a.out).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
