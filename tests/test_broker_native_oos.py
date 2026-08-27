from datetime import datetime, timezone, timedelta
from pathlib import Path
import csv, hashlib, json
from atlas.validation.broker_native_oos import audit_dataset, load_historical_news_csv

def _hash(p):
    h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()

def make_fixture(tmp_path):
    bars=tmp_path/'bars'; bars.mkdir()
    recs=[]; meta={'EURUSD':{'digits':5}}
    for tf,mins in [('D1',1440),('H4',240),('H1',60),('M15',15)]:
        p=bars/f'EURUSD_{tf}.csv'
        with p.open('w',newline='') as f:
            w=csv.writer(f); w.writerow(['time_utc','open','high','low','close','tick_volume','spread_points','real_volume'])
            t=datetime(2026,1,1,tzinfo=timezone.utc)
            for i in range(4):
                w.writerow([(t+timedelta(minutes=mins*i)).isoformat(),1,1.1,.9,1.0,100,8,0])
        recs.append({'symbol':'EURUSD','timeframe':tf,'rows':4,'first_bar_utc':'','last_bar_utc':'','file':str(p.relative_to(tmp_path)),'sha256':_hash(p)})
    (tmp_path/'manifest.json').write_text(json.dumps({'broker':'MT5_DEMO','account_id':'DEMO','symbol_metadata':meta,'records':recs}),encoding='utf-8')
    return tmp_path

def test_audit_passes_complete_hashed_dataset(tmp_path):
    a=audit_dataset(make_fixture(tmp_path)); assert a.ok; assert a.reason_codes==['DATASET_AUDIT_PASSED']

def test_audit_fails_hash_change(tmp_path):
    root=make_fixture(tmp_path); p=root/'bars/EURUSD_M15.csv'; p.write_text(p.read_text()+'\n',encoding='utf-8')
    a=audit_dataset(root); assert not a.ok; assert any(x.startswith('HASH_MISMATCH:EURUSD:M15') for x in a.reason_codes)

def test_news_is_fail_closed_when_missing(tmp_path):
    rows,reasons=load_historical_news_csv(None); assert rows==[]; assert reasons==['HISTORICAL_NEWS_UNAVAILABLE']
