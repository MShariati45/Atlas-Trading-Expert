"""Build Atlas's official four-currency scheduled-news bundle (zero AI calls).

Primary backbone:
- USD: U.S. BLS release calendar + Federal Reserve FOMC policy dates.
- EUR: ECB monetary-policy decision dates.
- CAD: Bank of Canada policy dates + Statistics Canada rolling CPI/LFS schedule.
- JPY: Bank of Japan policy dates + Statistics Bureau CPI/Labour Force schedules.

This is a conservative scheduled-news backbone, not a breaking-news wire. It makes
NO trades and NO AI calls. Every source is primary/official.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from atlas.services.official_calendar import parse_bls_ics
from atlas.services.official_four_currency_calendar import (
    official_policy_events_2026, japan_macro_events_2026, canada_macro_events_2026, parse_statcan_high_impact_schedule, required_family_coverage,
    FED_URL, ECB_URL, BOC_URL, STATCAN_URL, BOJ_URL, JP_LFS_URL, JP_CPI_URL,
    validate_source_markers,
)
from atlas.services.news_provider import JsonScheduledNewsProvider

BLS_ICS="https://www.bls.gov/schedule/news_release/bls.ics"
REQ={"USD","EUR","CAD","JPY"}

def fetch(url:str, timeout:float, accept:str="text/html,*/*") -> str:
    req=Request(url,headers={"User-Agent":"AtlasTradingExpert/0.24.2","Accept":accept})
    with urlopen(req,timeout=timeout) as r:
        return r.read().decode("utf-8",errors="replace")

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default='runtime/news_events.json'); ap.add_argument('--timeout',type=float,default=20.0); ap.add_argument('--horizon-days',type=int,default=120)
    a=ap.parse_args(); now=datetime.now(timezone.utc); horizon=now+timedelta(days=a.horizon_days)
    checks={}; events=[]
    # BLS dynamic official ICS
    try:
        txt=fetch(BLS_ICS,a.timeout,"text/calendar,*/*"); rows=parse_bls_ics(txt,source_url=BLS_ICS); events.extend(rows); checks['BLS']={'ok':True,'events':len(rows),'url':BLS_ICS}
    except Exception as e: checks['BLS']={'ok':False,'error':str(e),'url':BLS_ICS}
    # Validate primary policy/statistics source reachability + schedule identity.
    source_specs={
      'FED':(FED_URL,("2026","September","15-16")),
      'ECB':(ECB_URL,("2026","10/09/2026","monetary policy")),
      'BOC':(BOC_URL,("September 2, 2026","09:45")),
      'BOJ':(BOJ_URL,("2026","Sept.","Oct.")),
      'JP_LFS':(JP_LFS_URL,("2026","August 28","October 2")),
      'JP_CPI':(JP_CPI_URL,("Consumer Price Index","Schedule")),
    }
    for name,(url,markers) in source_specs.items():
        try:
            t=fetch(url,a.timeout); ok=validate_source_markers(t,markers); checks[name]={'ok':ok,'url':url,'error':None if ok else 'EXPECTED_MARKERS_NOT_FOUND'}
        except Exception as e: checks[name]={'ok':False,'url':url,'error':str(e)}
    # Official maintained 2026 schedule tables, only accepted when source checks pass.
    if all(checks.get(x,{}).get('ok') for x in ('FED','ECB','BOC','BOJ')):
        events.extend(official_policy_events_2026())
    if checks.get('JP_LFS',{}).get('ok') and checks.get('JP_CPI',{}).get('ok'):
        events.extend(japan_macro_events_2026())
    # Statistics Canada: official release-site health plus maintained 2026 CPI/LFS schedule.
    # The rolling Daily page changes markup frequently, so source reachability and
    # maintained primary-source dates are separated. This avoids a false green when
    # the page is reachable but the parser silently returns no major events.
    try:
        t=fetch(STATCAN_URL,a.timeout)
        dynamic_rows=parse_statcan_high_impact_schedule(t,now_year=now.year)
        checks['STATCAN']={'ok':True,'dynamic_events':len(dynamic_rows),'url':STATCAN_URL}
        events.extend(canada_macro_events_2026())
    except Exception as e: checks['STATCAN']={'ok':False,'error':str(e),'url':STATCAN_URL}
    # Deduplicate first, then filter the active horizon.
    uniq={}
    for e in events:
        uniq[(e.event_id,e.starts_at_utc.isoformat())]=e
    events=list(uniq.values())
    active_events=[e for e in events if now-timedelta(hours=2) <= e.starts_at_utc <= horizon]

    # Source health AND required event-family coverage must be complete. A reachable
    # website is not enough: the merged active calendar itself must contain each
    # critical family needed by the four-symbol Atlas watchlist.
    required_checks=('BLS','FED','ECB','BOC','BOJ','JP_LFS','JP_CPI','STATCAN')
    source_healthy=all(checks.get(k,{}).get('ok') for k in required_checks)
    family_coverage=required_family_coverage(active_events)
    family_healthy=all(family_coverage.values())
    healthy=source_healthy and family_healthy

    # Annotate event-specific blackout windows only after coverage validation.
    kept=[]
    for e in active_events:
        p=e.to_payload()
        if e.event_id.startswith('BOJ:'):
            # BoJ announcement time is not fixed. Block a broad 08:00-16:00 JST window around a noon anchor.
            p['blackout_before_minutes']=240; p['blackout_after_minutes']=240; p['open_trade_review_minutes']=360
        elif e.impact=='HIGH':
            p['blackout_before_minutes']=120; p['blackout_after_minutes']=30; p['open_trade_review_minutes']=120
        kept.append(p)

    payload={
      'generated_at_utc':now.isoformat(), 'valid_until_utc':(now+timedelta(hours=12)).isoformat(),
      'source_name':'Atlas official multi-source scheduled-news backbone',
      'source_url':'PRIMARY_SOURCE_MANIFEST_IN_PAYLOAD',
      'coverage_currencies':sorted(REQ),
      'coverage_status':'FULL_PRIMARY_BACKBONE' if healthy else ('PARTIAL_EVENT_FAMILY_COVERAGE' if source_healthy else 'PARTIAL_SOURCE_FAILURE'),
      'source_health':checks,
      'required_event_families':family_coverage,
      'events':sorted(kept,key=lambda r:r['starts_at_utc']),
      'notes':['Primary-source scheduled-news backbone; not a breaking-news wire.','Zero AI calls.','BoJ uses a conservative wide decision window because release time is not fixed.']
    }
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    if not healthy:
        status='PARTIAL_EVENT_FAMILY_COVERAGE' if source_healthy and not family_healthy else 'PARTIAL_SOURCE_FAILURE'
        print(json.dumps({'status':status,'output':str(out),'source_health':checks,'required_event_families':family_coverage},indent=2)); return 3
    provider=JsonScheduledNewsProvider(out,strict_freshness=True,min_validity_seconds=6*3600,strict_provenance=True,required_currencies=REQ)
    provider.events(now)
    if not provider.status.available:
        print(json.dumps({'status':'VALIDATION_FAILED','error':provider.status.error},indent=2)); return 4
    bycur={c:0 for c in REQ}
    for e in kept:
        for c in e.get('currencies',[]):
            if c in bycur: bycur[c]+=1
    print(json.dumps({'status':'FULL_OK','output':str(out),'events':len(kept),'events_by_currency':bycur,'coverage':sorted(REQ),'required_event_families':family_coverage,'zero_ai_calls':True},indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
