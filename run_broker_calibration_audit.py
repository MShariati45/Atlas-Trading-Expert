import argparse,json
from pathlib import Path
from atlas.services.broker_calibration_gate import audit_calibration
p=argparse.ArgumentParser(); p.add_argument('--csv',default='runtime/broker_spread_samples.csv'); p.add_argument('--policy',default='config/broker_cost_policy.json'); p.add_argument('--out',default='runtime/broker_calibration_audit.json'); p.add_argument('--min-samples',type=int,default=120)
a=p.parse_args(); result=audit_calibration(a.csv,a.policy,min_samples=a.min_samples); Path(a.out).parent.mkdir(parents=True,exist_ok=True); Path(a.out).write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps(result,indent=2)); raise SystemExit(0 if result['passed'] else 2)
