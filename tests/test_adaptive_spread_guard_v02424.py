import csv
from datetime import datetime, timezone
from atlas.services.adaptive_spread_guard import build_baseline_from_csv, AdaptiveSpreadGuard, classify_session


def test_session_classifier():
    assert classify_session(datetime(2026,1,1,2,tzinfo=timezone.utc)) == 'ASIA'
    assert classify_session(datetime(2026,1,1,9,tzinfo=timezone.utc)) == 'LONDON'
    assert classify_session(datetime(2026,1,1,15,tzinfo=timezone.utc)) == 'NEW_YORK'
    assert classify_session(datetime(2026,1,1,22,tzinfo=timezone.utc)) == 'ROLLOVER'


def test_baseline_ignores_shock_outliers(tmp_path):
    p=tmp_path/'s.csv'
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['utc_time','symbol','spread_points','tick_age_seconds']); w.writeheader()
        for i in range(150):
            w.writerow({'utc_time':'2026-08-24T15:00:00+00:00','symbol':'EURUSD','spread_points':5+(i%3),'tick_age_seconds':1})
        for i in range(4):
            w.writerow({'utc_time':'2026-08-24T15:00:00+00:00','symbol':'EURUSD','spread_points':100,'tick_age_seconds':1})
    b=build_baseline_from_csv(p,min_session_samples=60,min_all_samples=120)
    r=b['symbols']['EURUSD']['sessions']['NEW_YORK']
    assert r['median_points'] <= 6
    assert r['p95_points'] <= 7


def test_adaptive_guard_blocks_abnormal_multiple_and_tight_stop():
    b={'symbols':{'EURUSD':{'all':{'median_points':5,'p95_points':7},'sessions':{}}}}
    g=AdaptiveSpreadGuard(b)
    now=datetime(2026,8,24,9,tzinfo=timezone.utc)
    assert g.assess('EURUSD',5,now=now,stop_distance_points=100).status == 'NORMAL'
    assert g.assess('EURUSD',8,now=now,stop_distance_points=100).status == 'ELEVATED'
    assert g.assess('EURUSD',11,now=now,stop_distance_points=100).status == 'BLOCK'
    assert g.assess('EURUSD',6,now=now,stop_distance_points=20).status == 'BLOCK'
