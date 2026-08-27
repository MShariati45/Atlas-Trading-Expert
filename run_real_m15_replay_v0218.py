from __future__ import annotations
import csv, json, math
from collections import Counter, defaultdict
from dataclasses import asdict
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
START=datetime(2021,5,1,tzinfo=timezone.utc)
END=datetime(2021,6,15,6,0,tzinfo=timezone.utc)

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
        epoch=int(b.time_utc.timestamp())
        key=epoch//(minutes*60)
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
    def ensure_symbol(self,symbol):
        return SymbolSnapshot(symbol,0.00001,5,0.00001,1.0,0.01,100.0,0.01,0,0,True)
    def closed_bars(self,symbol,timeframe,count=300):
        if timeframe!='M15': raise ValueError(timeframe)
        a=max(0,self.i-count+1); return self.m15[a:self.i+1]
    def tick(self,symbol):
        b=self.m15[self.i]; return TickSnapshot(symbol,b.time_utc,b.close-0.00004,b.close+0.00004,b.close,b.tick_volume)

# Seed HTF strictly from history before replay start.
boot=HistoricalStructureBootstrapper()
h4_hist=[b for b in h4_all if b.time_utc < START]
h1_hist=[b for b in h1_all if b.time_utc < START]
assert len(h4_hist)>=100 and len(h1_hist)>=100
store=InMemoryStateStore(); h4=H4StructureAgent(store); h1=H1StructureAgent(store)
r4=boot.derive(h4_hist[-600:]); r1=boot.derive(h1_hist[-600:])
h4.seed('EURUSD',trend=r4.trend,origin=r4.origin,endpoint=r4.endpoint,control_pivot=r4.control_pivot)
h1.seed('EURUSD',trend=r1.trend,origin=r1.origin,endpoint=r1.endpoint,control_pivot=r1.control_pivot)
align=HTFAlignmentService(); fib=FibonacciRetracementEngine()

feed=ReplayFeed(rows); mstore=InMemoryStateStore(); m15=M15LiveSpecialistRuntime(feed,mstore)
# Pre-index HTF bars by final M15 open timestamp in bucket: H1 at hh:45, H4 bucket at x3:45.
h1_by_close={b.time_utc.replace(minute=45): b for b in h1_all}
h4_by_close={b.time_utc.replace(hour=b.time_utc.hour+3,minute=45): b for b in h4_all if b.time_utc.hour<=20}

agent_action=Counter(); agent_status=Counter(); pkg_states=Counter(); reasons=Counter();
unique_events=set(); event_rows=[]; package_events=[]; duplicate_count=0; conflict_count=0; confirmation_count=0
stop_pips=[]; trigger_age=[]; alignment_counts=Counter(); fib_states=Counter(); eligible_bars=0
last_ids={}

for i,b in enumerate(rows):
    if b.time_utc < START: continue
    if b.time_utc >= END: break
    feed.i=i
    # Only consume completed H1/H4 bars on their final M15 close.
    if b.time_utc in h4_by_close:
        hb=h4_by_close[b.time_utc]
        h4.handle(Event('H4_BAR_CLOSED',symbol='EURUSD',timeframe='H4',payload=candle_payload(hb)))
    if b.time_utc in h1_by_close:
        hb=h1_by_close[b.time_utc]
        h1.handle(Event('H1_BAR_CLOSED',symbol='EURUSD',timeframe='H1',payload=candle_payload(hb)))
    s4=H4StructureState.from_dict(store.get(h4._key('EURUSD')))
    s1=H1StructureState.from_dict(store.get(h1._key('EURUSD')))
    ar=align.evaluate('EURUSD',s4.to_dict(),s1.to_dict()); alignment_counts[ar.state]+=1
    if not ar.aligned or not s1.strategic_origin or not s1.strategic_endpoint:
        continue
    fc=fib.calculate(direction=s1.trend,origin=s1.strategic_origin.price,endpoint=s1.strategic_endpoint.price,current=b.close,aligned=True,correction_qualified=s1.correction_qualified,max_correction_depth=s1.correction_depth)
    fib_states[fc.state]+=1
    direction='LONG' if s1.trend=='BULLISH' else 'SHORT'
    if not (fc.broad_m15_activation or fc.new_flag_discovery_allowed) or fc.state=='STRUCTURE_RISK':
        continue
    eligible_bars+=1
    snap=m15.poll('EURUSD',direction,fc.retracement_pct,history_count=240,broad_m15_activation=fc.broad_m15_activation,new_flag_discovery_allowed=fc.new_flag_discovery_allowed,structure_risk=(fc.state=='STRUCTURE_RISK'))
    pkg=snap.coordinator; pkg_states[pkg['coordination_state']]+=1
    for rc in pkg.get('reason_codes',[]): reasons[rc]+=1
    duplicate_count += len(pkg.get('duplicates',[])); conflict_count += len(pkg.get('conflicts',[])); confirmation_count += len(pkg.get('confirmations',[]))
    for rep in snap.reports:
        agent_status[(rep['agent_id'],rep['status'])]+=1
        if rep['status'] in ('VALID_TRIGGER','EARLY_REVERSAL_CANDIDATE'):
            d=rep['data']; t=(d.get('bos_time') or d.get('structural_break_time') or d.get('confirmation_time') or d.get('neckline_break_time') or d.get('breakout_time'))
            entry=d.get('entry_reference') if d.get('entry_reference') is not None else d.get('trigger_entry_reference')
            eid=d.get('event_id') or f"{rep['agent_id']}|{t}|{entry}"
            if eid not in unique_events:
                unique_events.add(eid); agent_action[(rep['agent_id'],rep['status'])]+=1
                fs=d.get('final_stop')
                if entry is not None and fs is not None: stop_pips.append(abs(float(entry)-float(fs))/0.0001)
                event_rows.append({'time':b.time_utc.isoformat(),'agent':rep['agent_id'],'status':rep['status'],'event_id':eid,'entry':entry,'final_stop':fs,'pkg_state':pkg['coordination_state']})
    pt=pkg.get('primary_trigger')
    if pt and pt.get('event_id') and last_ids.get('primary')!=pt['event_id']:
        last_ids['primary']=pt['event_id']; package_events.append({'time':b.time_utc.isoformat(),**pt,'coordination_state':pkg['coordination_state'],'confirmations':len(pkg.get('confirmations',[])),'duplicates':len(pkg.get('duplicates',[])),'conflicts':len(pkg.get('conflicts',[]))})

summary={
 'dataset':{'source':'GitHub jaxontn/historical-Data EURUSD_M15.csv','start':START.isoformat(),'end':END.isoformat(),'m15_rows_total':len(rows),'replay_rows':sum(1 for x in rows if START<=x.time_utc<END)},
 'eligible_m15_bars':eligible_bars,
 'alignment_states':dict(alignment_counts),
 'fibonacci_states':dict(fib_states),
 'coordinator_states':dict(pkg_states),
 'reason_codes':dict(reasons),
 'unique_actionable_events':{f'{a}|{s}':n for (a,s),n in agent_action.items()},
 'duplicates_observed':duplicate_count,'conflicts_observed':conflict_count,'independent_confirmations_observed':confirmation_count,
 'stop_pips':{'count':len(stop_pips),'min':min(stop_pips) if stop_pips else None,'median':sorted(stop_pips)[len(stop_pips)//2] if stop_pips else None,'mean':sum(stop_pips)/len(stop_pips) if stop_pips else None,'max':max(stop_pips) if stop_pips else None},
 'primary_packages':len(package_events),
}
(ROOT/'real_m15_replay_summary_v0218.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
with (ROOT/'real_m15_actionable_events_v0218.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['time','agent','status','event_id','entry','final_stop','pkg_state']); w.writeheader(); w.writerows(event_rows)
with (ROOT/'real_m15_primary_packages_v0218.csv').open('w',newline='') as f:
    fields=['time','agent','status','pattern_type','direction','entry_reference','raw_stop_anchor','applied_buffer','final_stop','trigger_time','event_id','freshness','reason_code','coordination_state','confirmations','duplicates','conflicts']
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(package_events)
print(json.dumps(summary,indent=2))
