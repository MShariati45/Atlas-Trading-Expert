from datetime import datetime, timedelta, timezone
from atlas.market_data.mt5_feed import Candle, SymbolSnapshot
from atlas.services.live_static_zones import LiveStaticZoneBuilder, ZoneBuildConfig

class Feed:
    def __init__(self):
        t=datetime(2025,1,1,tzinfo=timezone.utc)
        self.b=[]
        # Repeated reactions around 1.1000/1.1010 with enough alternating pivots.
        vals=[1.09,1.101,1.092,1.1005,1.0915,1.1012,1.0922,1.1008,1.0918]*8
        prev=vals[0]
        for i,v in enumerate(vals[1:]):
            self.b.append(Candle(t+timedelta(hours=4*i),prev,max(prev,v)+0.0003,min(prev,v)-0.0003,v,100,2,0)); prev=v
    def closed_bars(self,symbol,timeframe,count=300): return self.b[-count:]
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,0.00001,5,0.00001,1,0.01,100,0.01,0,0,True)

def test_builder_finds_cacheable_reaction_zones():
    b=LiveStaticZoneBuilder(Feed(),ZoneBuildConfig(lookback_d1=80,lookback_h4=80,min_touches=3))
    svc=b.build('EURUSD')
    assert svc.zones
    assert all(z.touch_count>=3 for z in svc.zones)
    assert {'D1','H4'} & {z.timeframe for z in svc.zones}
