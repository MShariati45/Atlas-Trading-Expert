import csv,json
from atlas.services.broker_calibration_gate import audit_calibration

def write_csv(p, vals, age=1):
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['symbol','spread_points','tick_age_seconds']); w.writeheader()
        for s,v in vals:
            w.writerow({'symbol':s,'spread_points':v,'tick_age_seconds':age})

def policy(p):
    p.write_text(json.dumps({'symbols':{s:{'max_spread_points':m} for s,m in [('EURUSD',2),('USDJPY',4),('USDCAD',2),('XAUUSD',50)]}}),encoding='utf-8')

def test_pass(tmp_path):
    c=tmp_path/'c.csv'; p=tmp_path/'p.json'; policy(p)
    vals=[]
    for s in ['EURUSD','USDJPY','USDCAD','XAUUSD']:
        vals += [(s,1.0)]*3
    r=audit_calibration(c,p,min_samples=3) if False else None
    write_csv(c,vals); r=audit_calibration(c,p,min_samples=3)
    assert r['passed'] is True

def test_fail_closed_on_stale_and_high_p95(tmp_path):
    c=tmp_path/'c.csv'; p=tmp_path/'p.json'; policy(p)
    vals=[]
    for s in ['EURUSD','USDJPY','USDCAD','XAUUSD']: vals += [(s,100.0)]*3
    write_csv(c,vals,age=100); r=audit_calibration(c,p,min_samples=3)
    assert r['passed'] is False
    assert 'STALE_TICK_SAMPLES_PRESENT' in r['symbols']['EURUSD']['reasons']
