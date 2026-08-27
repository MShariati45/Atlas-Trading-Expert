from __future__ import annotations
import csv, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
from atlas.market_data.mt5_feed import Candle, SymbolSnapshot, TickSnapshot
from atlas.market_data.bootstrap import HistoricalStructureBootstrapper
from atlas.core.state_store import InMemoryStateStore
from atlas.agents.h4_structure import H4StructureAgent,H4StructureState
from atlas.agents.h1_structure import H1StructureAgent,H1StructureState
from atlas.agents.fibonacci import FibonacciRetracementEngine
from atlas.coordination.htf_alignment import HTFAlignmentService
from atlas.core.events import Event
from atlas.market_data.live_runtime import candle_payload
from atlas.market_data.m15_live_runtime import M15LiveSpecialistRuntime
ROOT=Path(__file__).resolve().parent
rows=[]
with (ROOT/'EURUSD_M15.csv').open() as f:
 for r in csv.reader(f):
  if not r: continue
  dt=datetime.strptime(r[0],'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
  rows.append(Candle(dt,float(r[1]),float(r[2]),float(r[3]),float(r[4]),int(float(r[5])),8,0))
rows.sort(key=lambda x:x.time_utc)
def aggregate(bars,minutes):
 out=[]; bucket=[]; cur=None
 for b in bars:
  k=int(b.time_utc.timestamp())//(minutes*60)
  if cur is None: cur=k
  if k!=cur:
   if bucket: out.append(Candle(bucket[0].time_utc,bucket[0].open,max(x.high for x in bucket),min(x.low for x in bucket),bucket[-1].close,sum(x.tick_volume for x in bucket),8,0))
   bucket=[];cur=k
  bucket.append(b)
 if bucket: out.append(Candle(bucket[0].time_utc,bucket[0].open,max(x.high for x in bucket),min(x.low for x in bucket),bucket[-1].close,sum(x.tick_volume for x in bucket),8,0))
 return out
h1_all=aggregate(rows,60); h4_all=aggregate(rows,240)
class Feed:
 def __init__(self): self.i=0
 def ensure_symbol(self,s): return SymbolSnapshot(s,0.00001,5,0.00001,1.0,0.01,100.0,0.01,0,0,True)
 def closed_bars(self,s,tf,count=300): return rows[max(0,self.i-count+1):self.i+1]
 def tick(self,s):
  b=rows[self.i]; return TickSnapshot(s,b.time_utc,b.close-.00004,b.close+.00004,b.close,b.tick_volume)

def run_window(center):
 start=center-timedelta(hours=18); end=center+timedelta(hours=12)
 boot=HistoricalStructureBootstrapper(); store=InMemoryStateStore(); h4=H4StructureAgent(store);h1=H1StructureAgent(store)
 h4hist=[b for b in h4_all if b.time_utc<start];h1hist=[b for b in h1_all if b.time_utc<start]
 try:
  r4=boot.derive(h4hist[-600:]);r1=boot.derive(h1hist[-600:])
 except Exception as e:return {'center':center.isoformat(),'error':str(e)}
 h4.seed('EURUSD',trend=r4.trend,origin=r4.origin,endpoint=r4.endpoint,control_pivot=r4.control_pivot)
 h1.seed('EURUSD',trend=r1.trend,origin=r1.origin,endpoint=r1.endpoint,control_pivot=r1.control_pivot)
 align=HTFAlignmentService();fib=FibonacciRetracementEngine();feed=Feed();mstore=InMemoryStateStore();m15=M15LiveSpecialistRuntime(feed,mstore)
 h1close={b.time_utc.replace(minute=45):b for b in h1_all if start<=b.time_utc.replace(minute=45)<end}
 h4close={b.time_utc.replace(hour=b.time_utc.hour+3,minute=45):b for b in h4_all if b.time_utc.hour<=20 and start<=b.time_utc.replace(hour=b.time_utc.hour+3,minute=45)<end}
 ev=[]; seen=set(); elig=0; states=Counter()
 # start processing a bit before start for m15 context availability but no HTF updates prior to start bootstrap
 for i,b in enumerate(rows):
  if b.time_utc<start: continue
  if b.time_utc>=end: break
  feed.i=i
  if b.time_utc in h4close:h4.handle(Event('H4_BAR_CLOSED',symbol='EURUSD',timeframe='H4',payload=candle_payload(h4close[b.time_utc])))
  if b.time_utc in h1close:h1.handle(Event('H1_BAR_CLOSED',symbol='EURUSD',timeframe='H1',payload=candle_payload(h1close[b.time_utc])))
  s4=H4StructureState.from_dict(store.get(h4._key('EURUSD')));s1=H1StructureState.from_dict(store.get(h1._key('EURUSD')));ar=align.evaluate('EURUSD',s4.to_dict(),s1.to_dict())
  if not ar.aligned or not s1.strategic_origin or not s1.strategic_endpoint: continue
  fc=fib.calculate(direction=s1.trend,origin=s1.strategic_origin.price,endpoint=s1.strategic_endpoint.price,current=b.close,aligned=True,correction_qualified=s1.correction_qualified,max_correction_depth=s1.correction_depth)
  if not (fc.broad_m15_activation or fc.new_flag_discovery_allowed) or fc.state=='STRUCTURE_RISK': continue
  elig+=1;direction='LONG' if s1.trend=='BULLISH' else 'SHORT'
  snap=m15.poll('EURUSD',direction,fc.retracement_pct,history_count=240,broad_m15_activation=fc.broad_m15_activation,new_flag_discovery_allowed=fc.new_flag_discovery_allowed,structure_risk=False)
  states[snap.coordinator['coordination_state']]+=1
  for rep in snap.reports:
   if rep['status']!='VALID_TRIGGER':continue
   d=rep['data'];pt=d.get('pattern_type') or ''
   if not (('PENNANT' in pt) or pt in {'ASCENDING_TRIANGLE','FALLING_WEDGE'}):continue
   t=d.get('structural_break_time') or d.get('breakout_time');entry=d.get('entry_reference');eid=d.get('event_id') or f"{rep['agent_id']}|{t}|{entry}|{pt}"
   if eid in seen:continue
   seen.add(eid);ev.append({'bar_time':b.time_utc.isoformat(),'agent':rep['agent_id'],'pattern_type':pt,'direction':direction,'fib_pct':fc.retracement_pct,'fib_state':fc.state,'entry':entry,'raw_stop_anchor':d.get('raw_stop_anchor'),'final_stop':d.get('final_stop'),'trigger_time':t,'event_id':eid,'coordination_state':snap.coordinator['coordination_state'],'primary':(snap.coordinator.get('primary_trigger') or {}).get('event_id')})
 return {'center':center.isoformat(),'start':start.isoformat(),'end':end.isoformat(),'eligible_bars':elig,'coordinator_states':dict(states),'events':ev}

raw=json.loads((ROOT/'raw_missing_family_candidates_v0221.json').read_text())
# Prefer recent distinct dates across all three families.
selected=[]; used=set()
for fam in ['PENNANT','ASCENDING_TRIANGLE','FALLING_WEDGE']:
 xs=[x for x in raw if x['family']==fam and datetime.fromisoformat(x['time']).year>=2020]
 for x in reversed(xs):
  day=x['time'][:10]
  if day in used: continue
  selected.append((fam,datetime.fromisoformat(x['time'])));used.add(day)
  if sum(1 for f,_ in selected if f==fam)>=8:break
results=[]
for fam,t in selected:
 r=run_window(t);r['target_family']=fam;results.append(r)
 print(fam,t.isoformat(),'eligible',r.get('eligible_bars'),'events',r.get('events'))
(ROOT/'targeted_gated_family_windows_v0221.json').write_text(json.dumps(results,indent=2))
