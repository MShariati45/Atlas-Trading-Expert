from __future__ import annotations
import csv, json, math, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
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
WINDOWS=[
 ('2015_A', datetime(2015,3,9,tzinfo=timezone.utc), datetime(2015,3,20,23,59,tzinfo=timezone.utc)),
 ('2015_B', datetime(2015,8,17,tzinfo=timezone.utc), datetime(2015,8,28,23,59,tzinfo=timezone.utc)),
 ('2017_A', datetime(2017,1,16,tzinfo=timezone.utc), datetime(2017,1,27,23,59,tzinfo=timezone.utc)),
 ('2019_A', datetime(2019,1,7,tzinfo=timezone.utc), datetime(2019,1,18,23,59,tzinfo=timezone.utc)),
 ('2019_B', datetime(2019,8,5,tzinfo=timezone.utc), datetime(2019,8,16,23,59,tzinfo=timezone.utc)),
]
SYMBOLS=['EURUSD']


def load(symbol):
    fn=ROOT/f'{symbol}_M15.csv'
    rows=[]
    with fn.open(newline='') as f:
        for r in csv.reader(f):
            if not r: continue
            dt=datetime.strptime(r[0],'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
            rows.append(Candle(dt,float(r[1]),float(r[2]),float(r[3]),float(r[4]),int(float(r[5])),8,0))
    rows.sort(key=lambda x:x.time_utc); return rows

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

class ReplayFeed:
    def __init__(self,m15): self.m15=m15; self.i=0
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,0.00001,5,0.00001,1.0,0.01,100.0,0.01,0,0,True)
    def closed_bars(self,symbol,timeframe,count=300):
        a=max(0,self.i-count+1); return self.m15[a:self.i+1]
    def tick(self,symbol):
        b=self.m15[self.i]; return TickSnapshot(symbol,b.time_utc,b.close-0.00004,b.close+0.00004,b.close,b.tick_volume)

def resolve_outcome(rows, idx, direction, entry, stop, max_bars=480):
    risk=abs(entry-stop)
    if risk<=0: return ('INVALID',0,None)
    target=entry+2*risk if direction=='LONG' else entry-2*risk
    mfe=0.0; mae=0.0
    for j in range(idx+1,min(len(rows),idx+1+max_bars)):
        b=rows[j]
        if direction=='LONG':
            fav=(b.high-entry)/risk; adv=(entry-b.low)/risk
            hit_sl=b.low<=stop; hit_tp=b.high>=target
        else:
            fav=(entry-b.low)/risk; adv=(b.high-entry)/risk
            hit_sl=b.high>=stop; hit_tp=b.low<=target
        mfe=max(mfe,fav); mae=max(mae,adv)
        if hit_sl and hit_tp: return ('LOSS_AMBIGUOUS',-1.0,(mfe,mae,j-idx))
        if hit_sl: return ('LOSS',-1.0,(mfe,mae,j-idx))
        if hit_tp: return ('WIN',2.0,(mfe,mae,j-idx))
    return ('UNRESOLVED',0.0,(mfe,mae,min(max_bars,len(rows)-idx-1)))

def replay(symbol, rows, label, start, end):
    h1_all=aggregate(rows,60); h4_all=aggregate(rows,240)
    boot=HistoricalStructureBootstrapper(); store=InMemoryStateStore(); h4=H4StructureAgent(store); h1=H1StructureAgent(store)
    h4_hist=[b for b in h4_all if b.time_utc<start]; h1_hist=[b for b in h1_all if b.time_utc<start]
    if len(h4_hist)<100 or len(h1_hist)<100: return None
    r4=boot.derive(h4_hist[-600:]); r1=boot.derive(h1_hist[-600:])
    h4.seed(symbol,trend=r4.trend,origin=r4.origin,endpoint=r4.endpoint,control_pivot=r4.control_pivot)
    h1.seed(symbol,trend=r1.trend,origin=r1.origin,endpoint=r1.endpoint,control_pivot=r1.control_pivot)
    align=HTFAlignmentService(); fib=FibonacciRetracementEngine(); feed=ReplayFeed(rows); m15=M15LiveSpecialistRuntime(feed,InMemoryStateStore())
    h1_by_close={b.time_utc.replace(minute=45):b for b in h1_all}
    h4_by_close={b.time_utc.replace(hour=b.time_utc.hour+3,minute=45):b for b in h4_all if b.time_utc.hour<=20}
    eligible=0; align_ct=Counter(); fib_ct=Counter(); pkg_ct=Counter(); reasons=Counter(); seen=set(); events=[]
    for i,b in enumerate(rows):
        if b.time_utc<start: continue
        if b.time_utc>end: break
        feed.i=i
        if b.time_utc in h4_by_close: h4.handle(Event('H4_BAR_CLOSED',symbol=symbol,timeframe='H4',payload=candle_payload(h4_by_close[b.time_utc])))
        if b.time_utc in h1_by_close: h1.handle(Event('H1_BAR_CLOSED',symbol=symbol,timeframe='H1',payload=candle_payload(h1_by_close[b.time_utc])))
        s4=H4StructureState.from_dict(store.get(h4._key(symbol))); s1=H1StructureState.from_dict(store.get(h1._key(symbol)))
        ar=align.evaluate(symbol,s4.to_dict(),s1.to_dict()); align_ct[ar.state]+=1
        if not ar.aligned or not s1.strategic_origin or not s1.strategic_endpoint: continue
        fc=fib.calculate(direction=s1.trend,origin=s1.strategic_origin.price,endpoint=s1.strategic_endpoint.price,current=b.close,aligned=True,correction_qualified=s1.correction_qualified,max_correction_depth=s1.correction_depth)
        fib_ct[fc.state]+=1
        direction='LONG' if s1.trend=='BULLISH' else 'SHORT'
        if not (fc.broad_m15_activation or fc.new_flag_discovery_allowed) or fc.state=='STRUCTURE_RISK': continue
        eligible+=1
        snap=m15.poll(symbol,direction,fc.retracement_pct,history_count=240,broad_m15_activation=fc.broad_m15_activation,new_flag_discovery_allowed=fc.new_flag_discovery_allowed,structure_risk=False)
        pkg=snap.coordinator; pkg_ct[pkg['coordination_state']]+=1
        for rc in pkg.get('reason_codes',[]): reasons[rc]+=1
        pt=pkg.get('primary_trigger')
        if not pt or pkg.get('coordination_state')!='READY_FOR_SUPERVISOR_REVIEW': continue
        eid=pt.get('event_id')
        if not eid or eid in seen: continue
        seen.add(eid)
        entry=pt.get('entry_reference'); stop=pt.get('final_stop')
        if entry is None or stop is None: continue
        outcome,rval,extra=resolve_outcome(rows,i,direction,float(entry),float(stop))
        risk_pips=abs(float(entry)-float(stop))/0.0001
        events.append({
            'symbol':symbol,'window':label,'time':b.time_utc.isoformat(),'agent':pt.get('agent'),'pattern':pt.get('pattern_type'),'direction':direction,
            'entry':entry,'stop':stop,'stop_pips':risk_pips,'fib_state':fc.state,'fib_pct':fc.retracement_pct,'outcome':outcome,'R':rval,
            'mfe_R': extra[0] if extra else None,'mae_R':extra[1] if extra else None,'bars_to_resolution':extra[2] if extra else None,'event_id':eid
        })
    return {'symbol':symbol,'window':label,'start':start.isoformat(),'end':end.isoformat(),'bars':sum(1 for x in rows if start<=x.time_utc<=end),'eligible':eligible,'alignment':dict(align_ct),'fib':dict(fib_ct),'packages':dict(pkg_ct),'reasons':dict(reasons),'events':events}

all_results=[]; all_events=[]
for sym in SYMBOLS:
    rows=load(sym)
    for label,start,end in WINDOWS:
        print('RUN',sym,label,flush=True)
        r=replay(sym,rows,label,start,end)
        if r:
            all_results.append(r); all_events.extend(r['events'])
            print(' -> eligible',r['eligible'],'events',len(r['events']),flush=True)

# summaries
resolved=[e for e in all_events if e['outcome'] in ('WIN','LOSS','LOSS_AMBIGUOUS')]
wins=sum(e['outcome']=='WIN' for e in resolved); losses=len(resolved)-wins
summary={
 'windows':len(all_results),'symbols':SYMBOLS,'total_eligible_bars':sum(r['eligible'] for r in all_results),'supervisor_ready_events':len(all_events),
 'resolved_events':len(resolved),'wins':wins,'losses':losses,'win_rate_pct':(wins/len(resolved)*100 if resolved else None),
 'gross_R_sum':sum(e['R'] for e in resolved),'expectancy_R':(sum(e['R'] for e in resolved)/len(resolved) if resolved else None),
 'unresolved':sum(e['outcome']=='UNRESOLVED' for e in all_events),
 'stop_pips':{},'by_symbol':{},'by_agent':{},'by_pattern':{},'rejection_reason_counts':dict(sum((Counter(r['reasons']) for r in all_results),Counter())),
}
sp=[e['stop_pips'] for e in all_events]
if sp: summary['stop_pips']={'count':len(sp),'min':min(sp),'median':statistics.median(sp),'mean':statistics.mean(sp),'p90':sorted(sp)[max(0,math.ceil(.9*len(sp))-1)],'max':max(sp)}
for keyname,keyfn in [('by_symbol',lambda e:e['symbol']),('by_agent',lambda e:e['agent']),('by_pattern',lambda e:e['pattern'])]:
    groups=defaultdict(list)
    for e in all_events: groups[keyfn(e)].append(e)
    out={}
    for k,es in groups.items():
        rs=[e for e in es if e['outcome'] in ('WIN','LOSS','LOSS_AMBIGUOUS')]; w=sum(e['outcome']=='WIN' for e in rs)
        out[str(k)]={'events':len(es),'resolved':len(rs),'wins':w,'losses':len(rs)-w,'win_rate_pct':w/len(rs)*100 if rs else None,'gross_R_sum':sum(e['R'] for e in rs),'expectancy_R':sum(e['R'] for e in rs)/len(rs) if rs else None,'median_stop_pips':statistics.median([e['stop_pips'] for e in es]) if es else None}
    summary[keyname]=out

(ROOT/'multisymbol_calibration_extra_v0222.json').write_text(json.dumps({'summary':summary,'windows':[{k:v for k,v in r.items() if k!='events'} for r in all_results]},indent=2),encoding='utf-8')
with (ROOT/'multisymbol_events_extra_v0222.csv').open('w',newline='') as f:
    fields=list(all_events[0].keys()) if all_events else ['symbol']
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(all_events)
print(json.dumps(summary,indent=2))
