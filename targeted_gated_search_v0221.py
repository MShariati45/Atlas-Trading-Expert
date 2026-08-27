from __future__ import annotations
import csv, json, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from atlas.market_data.mt5_feed import Candle, SymbolSnapshot, TickSnapshot
from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.core.state_store import InMemoryStateStore
from atlas.agents.h4_structure import H4StructureAgent, H4StructureState
from atlas.agents.h1_structure import H1StructureAgent, H1StructureState
from atlas.agents.fibonacci import FibonacciRetracementEngine
from atlas.coordination.htf_alignment import HTFAlignmentService
from atlas.core.events import Event
from atlas.market_data.live_runtime import candle_payload
from atlas.market_data.m15_live_runtime import M15LiveSpecialistRuntime

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'EURUSD_M15.csv'
START=datetime.fromisoformat(sys.argv[1]).replace(tzinfo=timezone.utc)
END=datetime.fromisoformat(sys.argv[2]).replace(tzinfo=timezone.utc)
rows=[]
with SRC.open(newline='') as f:
    for r in csv.reader(f):
        if not r: continue
        dt=datetime.strptime(r[0],'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
        rows.append(Candle(dt,float(r[1]),float(r[2]),float(r[3]),float(r[4]),int(float(r[5])),8,0))
rows.sort(key=lambda x:x.time_utc)

def aggregate(bars, minutes):
    out=[]; bucket=[]; cur=None
    for b in bars:
        key=int(b.time_utc.timestamp())//(minutes*60)
        if cur is None: cur=key
        if key!=cur:
            if bucket: out.append(Candle(bucket[0].time_utc,bucket[0].open,max(x.high for x in bucket),min(x.low for x in bucket),bucket[-1].close,sum(x.tick_volume for x in bucket),8,0))
            bucket=[]; cur=key
        bucket.append(b)
    if bucket: out.append(Candle(bucket[0].time_utc,bucket[0].open,max(x.high for x in bucket),min(x.low for x in bucket),bucket[-1].close,sum(x.tick_volume for x in bucket),8,0))
    return out
h1_all=aggregate(rows,60); h4_all=aggregate(rows,240)
class ReplayFeed:
    def __init__(self,m15): self.m15=m15; self.i=0
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,0.00001,5,0.00001,1.0,0.01,100.0,0.01,0,0,True)
    def closed_bars(self,symbol,timeframe,count=300):
        a=max(0,self.i-count+1); return self.m15[a:self.i+1]
    def tick(self,symbol):
        b=self.m15[self.i]; return TickSnapshot(symbol,b.time_utc,b.close-0.00004,b.close+0.00004,b.close,b.tick_volume)
boot=HistoricalStructureBootstrapper()
h4_hist=[b for b in h4_all if b.time_utc < START]; h1_hist=[b for b in h1_all if b.time_utc < START]
if len(h4_hist)<100 or len(h1_hist)<100: raise SystemExit('not enough seed')
store=InMemoryStateStore(); h4=H4StructureAgent(store); h1=H1StructureAgent(store)
r4=boot.derive(h4_hist[-600:]); r1=boot.derive(h1_hist[-600:])
h4.seed('EURUSD',trend=r4.trend,origin=r4.origin,endpoint=r4.endpoint,control_pivot=r4.control_pivot)
h1.seed('EURUSD',trend=r1.trend,origin=r1.origin,endpoint=r1.endpoint,control_pivot=r1.control_pivot)
align=HTFAlignmentService(); fib=FibonacciRetracementEngine()
feed=ReplayFeed(rows); mstore=InMemoryStateStore(); m15=M15LiveSpecialistRuntime(feed,mstore)
h1_by_close={b.time_utc.replace(minute=45): b for b in h1_all}
h4_by_close={b.time_utc.replace(hour=b.time_utc.hour+3,minute=45): b for b in h4_all if b.time_utc.hour<=20}
missing={'PENNANT','BULL_PENNANT','BEAR_PENNANT','ASCENDING_TRIANGLE','FALLING_WEDGE'}
events=[]; seen=set(); eligible=0; pats=Counter()
for i,b in enumerate(rows):
    if b.time_utc < START: continue
    if b.time_utc >= END: break
    feed.i=i
    if b.time_utc in h4_by_close: h4.handle(Event('H4_BAR_CLOSED',symbol='EURUSD',timeframe='H4',payload=candle_payload(h4_by_close[b.time_utc])))
    if b.time_utc in h1_by_close: h1.handle(Event('H1_BAR_CLOSED',symbol='EURUSD',timeframe='H1',payload=candle_payload(h1_by_close[b.time_utc])))
    s4=H4StructureState.from_dict(store.get(h4._key('EURUSD'))); s1=H1StructureState.from_dict(store.get(h1._key('EURUSD')))
    ar=align.evaluate('EURUSD',s4.to_dict(),s1.to_dict())
    if not ar.aligned or not s1.strategic_origin or not s1.strategic_endpoint: continue
    fc=fib.calculate(direction=s1.trend,origin=s1.strategic_origin.price,endpoint=s1.strategic_endpoint.price,current=b.close,aligned=True,correction_qualified=s1.correction_qualified,max_correction_depth=s1.correction_depth)
    if not (fc.broad_m15_activation or fc.new_flag_discovery_allowed) or fc.state=='STRUCTURE_RISK': continue
    eligible += 1
    direction='LONG' if s1.trend=='BULLISH' else 'SHORT'
    snap=m15.poll('EURUSD',direction,fc.retracement_pct,history_count=240,broad_m15_activation=fc.broad_m15_activation,new_flag_discovery_allowed=fc.new_flag_discovery_allowed,structure_risk=False)
    for rep in snap.reports:
        if rep['status'] != 'VALID_TRIGGER': continue
        d=rep['data']; pt=d.get('pattern_type') or ''
        pats[pt]+=1
        t=d.get('bos_time') or d.get('structural_break_time') or d.get('confirmation_time') or d.get('neckline_break_time') or d.get('breakout_time')
        entry=d.get('entry_reference') if d.get('entry_reference') is not None else d.get('trigger_entry_reference')
        eid=d.get('event_id') or f"{rep['agent_id']}|{t}|{entry}|{pt}"
        if eid in seen: continue
        seen.add(eid)
        if ('PENNANT' in pt) or pt in {'ASCENDING_TRIANGLE','FALLING_WEDGE'}:
            events.append({'bar_time':b.time_utc.isoformat(),'agent':rep['agent_id'],'pattern_type':pt,'direction':direction,'fib_pct':fc.retracement_pct,'fib_state':fc.state,'status':rep['status'],'entry':entry,'raw_stop_anchor':d.get('raw_stop_anchor') or d.get('stop_anchor'),'final_stop':d.get('final_stop'),'trigger_time':t,'event_id':eid,'coordination_state':snap.coordinator.get('coordination_state'),'primary_trigger':(snap.coordinator.get('primary_trigger') or {}).get('event_id')})
            if len(events)>=8:
                break
    if len(events)>=8: break
print(json.dumps({'start':START.isoformat(),'end':END.isoformat(),'eligible':eligible,'patterns_seen':dict(pats),'target_events':events},indent=2))
