"""Refresh Atlas live scheduled-news JSON from a configured JSON endpoint.

This is provider-neutral and makes no AI calls. The endpoint must return either:
  {"generated_at_utc":"...","valid_until_utc":"...","events":[...]}
or an equivalent object with those fields. Use a licensed/reliable calendar feed.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.services.news_mapping import currencies_for_symbols


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--url', default=os.getenv('ATLAS_NEWS_URL'))
    p.add_argument('--bearer-env', default='ATLAS_NEWS_BEARER_TOKEN')
    p.add_argument('--output', default='runtime/news_events.json')
    p.add_argument('--timeout', type=float, default=15.0)
    p.add_argument('--min-valid-hours', type=float, default=6.0)
    args=p.parse_args()
    if not args.url:
        print('NOT CONFIGURED: set ATLAS_NEWS_URL or pass --url to a trusted/licensed JSON economic-calendar feed.')
        return 2
    headers={'Accept':'application/json','User-Agent':'AtlasTradingExpert/0.24.2'}
    token=os.getenv(args.bearer_env)
    if token: headers['Authorization']=f'Bearer {token}'
    req=Request(args.url,headers=headers,method='GET')
    with urlopen(req,timeout=args.timeout) as r:
        raw=r.read().decode('utf-8')
    payload=json.loads(raw)
    if not isinstance(payload,dict):
        raise ValueError('Live news endpoint must return a JSON object with schedule metadata')
    # Require source metadata; never stamp freshness locally and pretend stale data is current.
    if not payload.get('generated_at_utc') or not payload.get('valid_until_utc'):
        raise ValueError('Endpoint must provide generated_at_utc and valid_until_utc')
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+'.tmp')
    tmp.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    provider=JsonScheduledNewsProvider(tmp,strict_freshness=True,min_validity_seconds=int(args.min_valid_hours*3600),strict_provenance=True,required_currencies=currencies_for_symbols(['EURUSD','USDJPY','USDCAD','XAUUSD']))
    provider.events(datetime.now(timezone.utc))
    if not provider.status.available:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(provider.status.error or 'LIVE_NEWS_VALIDATION_FAILED')
    tmp.replace(out)
    print(json.dumps({'status':'OK','output':str(out),'events':provider.status.event_count,'generated_at_utc':provider.status.source_generated_at_utc,'valid_until_utc':provider.status.valid_until_utc},indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
