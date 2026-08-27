from datetime import datetime, timezone
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard

baseline={
 'symbols':{
  'EURUSD':{
   'all':{'median_points':5.0,'p95_points':7.0,'samples':500},
   'sessions':{'NEW_YORK':{'median_points':5.0,'p95_points':7.0,'samples':200}}
  }
 }
}
g=AdaptiveSpreadGuard(baseline, elevated_multiple=1.5, block_multiple=2.0, p95_block_multiple=1.5, max_spread_to_stop_ratio=.25)
now=datetime(2026,8,24,15,0,tzinfo=timezone.utc)
for spread in (5,8,11,20):
    d=g.assess('EURUSD',spread,now=now,stop_distance_points=100)
    print(spread,d.status,d.allowed,d.block_threshold_points,d.reasons)
assert g.assess('EURUSD',5,now=now,stop_distance_points=100).allowed is True
assert g.assess('EURUSD',8,now=now,stop_distance_points=100).status == 'ELEVATED'
assert g.assess('EURUSD',11,now=now,stop_distance_points=100).allowed is False
assert g.assess('EURUSD',20,now=now,stop_distance_points=100).allowed is False
assert g.assess('EURUSD',6,now=now,stop_distance_points=20).allowed is False
print('PASS - adaptive spread guard selfcheck')
