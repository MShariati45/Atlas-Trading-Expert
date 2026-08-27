from __future__ import annotations

import argparse,csv,json
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from pathlib import Path

from atlas.validation.broker_native_oos import audit_dataset, load_historical_news_csv, parse_dt
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
from atlas.services.live_static_zones import LiveStaticZoneBuilder
from atlas.services.news_guard import NewsGuard,NewsEvent

TF_CLOSE_OFFSET={'M15':timedelta(minutes=0),'H1':timedelta(minutes=45),'H4':timedelta(hours=3,minutes=45),'D1':timedelta(hours=23,minutes=45)}

def read_bars(path:Path)->list[Candle]:
    out=[]
    with path.open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            out.append(Candle(parse_dt(r['time_utc']),float(r['open']),float(r['high']),float(r['low']),float(r['close']),int(float(r.get('tick_volume') or 0)),int(float(r.get('spread_points') or 0)),int(float(r.get('real_volume') or 0))))
    return out

class NativeReplayFeed:
    def __init__(self,symbol:str,bars:dict[str,list[Candle]],point:float,digits:int):
        self.symbol=symbol; self.bars=bars; self.now=bars['M15'][0].time_utc; self.point=point; self.digits=digits
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,self.point,self.digits,self.point,1.0,0.01,100.0,0.01,0,0,True)
    def closed_bars(self,symbol,timeframe,count=300):
        rows=[b for b in self.bars[timeframe] if b.time_utc+TF_CLOSE_OFFSET[timeframe] <= self.now]
        return rows[-count:]
    def tick(self,symbol):
        rows=self.closed_bars(symbol,'M15',1); b=rows[-1]
        spread=max(b.spread_points,1)*self.point
        return TickSnapshot(symbol,self.now,b.close-spread/2,b.close+spread/2,b.close,b.tick_volume)

def news_events(rows:list[dict],symbol:str)->list[NewsEvent]:
    currencies={symbol[:3],symbol[3:6]}
    out=[]
    for r in rows:
        if r['currency'] not in currencies: continue
        out.append(NewsEvent(r['event_id'] or f"{r['currency']}:{r['event_time_utc']}",parse_dt(r['event_time_utc']),frozenset([symbol]),r['impact'],r['title']))
    return out

def main():
    ap=argparse.ArgumentParser(description='Atlas broker-native OOS chronological replay (read-only research)')
    ap.add_argument('--dataset',required=True); ap.add_argument('--symbol',required=True); ap.add_argument('--historical-news',default=None)
    ap.add_argument('--start',required=True); ap.add_argument('--end',required=True); ap.add_argument('--out',default='broker_native_oos_result.json')
    args=ap.parse_args(); root=Path(args.dataset); audit=audit_dataset(root)
    if not audit.ok: raise SystemExit('DATASET_AUDIT_FAILED: '+','.join(audit.reason_codes))
    nrows,nreasons=load_historical_news_csv(args.historical_news); fully_gated='HISTORICAL_NEWS_LOADED' in nreasons
    manifest=json.loads((root/'manifest.json').read_text()); rec={(r['symbol'],r['timeframe']):r for r in manifest['records']}
    s=args.symbol; meta=manifest['symbol_metadata'][s]; point=float(meta.get('point',10**(-int(meta.get('digits',5))))); digits=int(meta.get('digits',5))
    bars={tf:read_bars(root/rec[(s,tf)]['file']) for tf in ('D1','H4','H1','M15')}
    start=parse_dt(args.start); end=parse_dt(args.end)
    boot=HistoricalStructureBootstrapper(); store=InMemoryStateStore(); h4=H4StructureAgent(store); h1=H1StructureAgent(store)
    pre4=[b for b in bars['H4'] if b.time_utc+TF_CLOSE_OFFSET['H4']<start]; pre1=[b for b in bars['H1'] if b.time_utc+TF_CLOSE_OFFSET['H1']<start]
    if len(pre4)<100 or len(pre1)<100: raise SystemExit('INSUFFICIENT_BOOTSTRAP_HISTORY')
    r4=boot.derive(pre4[-600:]); r1=boot.derive(pre1[-600:]); h4.seed(s,trend=r4.trend,origin=r4.origin,endpoint=r4.endpoint,control_pivot=r4.control_pivot); h1.seed(s,trend=r1.trend,origin=r1.origin,endpoint=r1.endpoint,control_pivot=r1.control_pivot)
    feed=NativeReplayFeed(s,bars,point,digits); m15=M15LiveSpecialistRuntime(feed,InMemoryStateStore()); align=HTFAlignmentService(); fib=FibonacciRetracementEngine(); zone_builder=LiveStaticZoneBuilder(feed); ng=NewsGuard(); ng.set_events(news_events(nrows,s))
    h1close={b.time_utc+TF_CLOSE_OFFSET['H1']:b for b in bars['H1']}; h4close={b.time_utc+TF_CLOSE_OFFSET['H4']:b for b in bars['H4']}
    events=[]; reasons=Counter(); eligible=0
    for b in bars['M15']:
        if b.time_utc<start: continue
        if b.time_utc>end: break
        feed.now=b.time_utc
        if b.time_utc in h4close: h4.handle(Event('H4_BAR_CLOSED',symbol=s,timeframe='H4',payload=candle_payload(h4close[b.time_utc])))
        if b.time_utc in h1close: h1.handle(Event('H1_BAR_CLOSED',symbol=s,timeframe='H1',payload=candle_payload(h1close[b.time_utc])))
        s4=H4StructureState.from_dict(store.get(h4._key(s))); s1=H1StructureState.from_dict(store.get(h1._key(s))); ar=align.evaluate(s,s4.to_dict(),s1.to_dict())
        if not ar.aligned or not s1.strategic_origin or not s1.strategic_endpoint: continue
        fc=fib.calculate(direction=s1.trend,origin=s1.strategic_origin.price,endpoint=s1.strategic_endpoint.price,current=b.close,aligned=True,correction_qualified=s1.correction_qualified,max_correction_depth=s1.correction_depth)
        if not (fc.broad_m15_activation or fc.new_flag_discovery_allowed) or fc.state=='STRUCTURE_RISK': continue
        eligible+=1; direction='LONG' if s1.trend=='BULLISH' else 'SHORT'
        snap=m15.poll(s,direction,fc.retracement_pct,history_count=240,broad_m15_activation=fc.broad_m15_activation,new_flag_discovery_allowed=fc.new_flag_discovery_allowed,structure_risk=False)
        pkg=snap.coordinator; pt=pkg.get('primary_trigger')
        if pkg.get('coordination_state')!='READY_FOR_SUPERVISOR_REVIEW' or not pt: continue
        entry=float(pt['entry_reference']); stop=float(pt['final_stop']); target=entry+2*abs(entry-stop) if direction=='LONG' else entry-2*abs(entry-stop)
        zones=zone_builder.build(s); za=zones.assess_target_path(entry,target,direction); na=ng.assess(s,b.time_utc) if fully_gated else None
        rc=[]
        if not za.clear_for_target: rc.append('STATIC_ZONE_BLOCKED')
        if na is None: rc.append('NEWS_DATA_UNAVAILABLE')
        elif not na.clear_for_new_entry: rc.append('NEWS_BLACKOUT_ACTIVE')
        events.append({'time':b.time_utc.isoformat(),'direction':direction,'agent':pt.get('agent'),'pattern':pt.get('pattern_type'),'entry':entry,'stop':stop,'target':target,'fib_state':fc.state,'fib_pct':fc.retracement_pct,'static_zone_ok':za.clear_for_target,'news_ok':None if na is None else na.clear_for_new_entry,'fully_gated':fully_gated,'reason_codes':rc,'event_id':pt.get('event_id')})
        for x in rc: reasons[x]+=1
    result={'schema_version':'0.22.6','symbol':s,'start':start.isoformat(),'end':end.isoformat(),'dataset_audit':asdict(audit),'historical_news_reason_codes':nreasons,'fully_gated':fully_gated,'eligible_m15_bars':eligible,'review_ready_events':len(events),'reason_counts':dict(reasons),'events':events,'note':'No profitability conclusion should be drawn unless fully_gated is true and future-bar outcome resolution is run.'}
    Path(args.out).write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps({k:v for k,v in result.items() if k!='events'},indent=2))
if __name__=='__main__': main()
