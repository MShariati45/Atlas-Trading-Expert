from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.services.live_news import LiveNewsGuardService


def test_missing_news_source_returns_pending_not_clear():
    p=JsonScheduledNewsProvider('/definitely/missing/news.json')
    r=LiveNewsGuardService(p).assess('EURUSD',datetime.now(timezone.utc))
    assert r.gate is None
    assert 'NEWS_DATA_UNAVAILABLE' in r.reason_codes


def test_high_impact_event_blocks_entry():
    with TemporaryDirectory() as d:
        now=datetime.now(timezone.utc)
        path=Path(d)/'news.json'
        path.write_text(json.dumps({'events':[{'event_id':'N1','starts_at_utc':(now+timedelta(minutes=10)).isoformat(),'affected_symbols':['EURUSD'],'impact':'HIGH','title':'test'}]}))
        r=LiveNewsGuardService(JsonScheduledNewsProvider(path)).assess('EURUSD',now)
        assert r.gate is False
        assert 'NEWS_BLACKOUT_ACTIVE' in r.reason_codes


def test_strict_live_news_requires_source_validity_metadata():
    with TemporaryDirectory() as d:
        now=datetime.now(timezone.utc)
        path=Path(d)/'news.json'
        path.write_text(json.dumps({'events':[]}))
        p=JsonScheduledNewsProvider(path, strict_freshness=True, min_validity_seconds=3600)
        assert p.events(now)==[]
        assert p.status.available is False
        assert 'METADATA_REQUIRED' in (p.status.error or '')


def test_strict_live_news_accepts_fresh_schedule():
    with TemporaryDirectory() as d:
        now=datetime.now(timezone.utc)
        path=Path(d)/'news.json'
        path.write_text(json.dumps({
            'generated_at_utc': now.isoformat(),
            'valid_until_utc': (now+timedelta(hours=12)).isoformat(),
            'events': []
        }))
        p=JsonScheduledNewsProvider(path, strict_freshness=True, min_validity_seconds=6*3600)
        assert p.events(now)==[]
        assert p.status.available is True
        assert p.status.valid_until_utc is not None
