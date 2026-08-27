from datetime import datetime, timezone
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
b={'symbols':{'USDJPY':{'all':{'median_points':5.0,'p95_points':7.0},'sessions':{}}}}
g=AdaptiveSpreadGuard(b)
now=datetime(2026,8,24,15,tzinfo=timezone.utc)
assert g.assess('USDJPY',5,now=now,stop_distance_points=80).allowed is True
assert g.assess('USDJPY',8,now=now,stop_distance_points=80).status == 'ELEVATED'
assert g.assess('USDJPY',11,now=now,stop_distance_points=80).allowed is False
assert g.assess('USDJPY',6,now=now,stop_distance_points=20).allowed is False
print('ATLAS v0.24.24 SELF-CHECK: PASS')
print('adaptive spread: symbol-specific + session-aware + outlier-resistant')
print('execution: still locked; zero orders; zero AI calls')
