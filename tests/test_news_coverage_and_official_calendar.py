from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from atlas.services.news_provider import JsonScheduledNewsProvider
from atlas.services.news_mapping import currencies_for_symbols
from atlas.services.official_calendar import parse_bls_ics


def test_currency_mapping_for_four_symbol_watchlist():
    assert currencies_for_symbols(["EURUSD", "USDJPY", "USDCAD", "XAUUSD"]) == frozenset({"USD", "EUR", "JPY", "CAD"})


def test_strict_provider_rejects_partial_currency_coverage():
    with TemporaryDirectory() as d:
        now = datetime.now(timezone.utc)
        path = Path(d) / "news.json"
        path.write_text(json.dumps({
            "generated_at_utc": now.isoformat(),
            "valid_until_utc": (now + timedelta(hours=12)).isoformat(),
            "source_name": "Official USD only",
            "source_url": "https://example.test",
            "coverage_currencies": ["USD"],
            "events": [],
        }))
        p = JsonScheduledNewsProvider(path, strict_freshness=True, min_validity_seconds=3600, strict_provenance=True, required_currencies={"USD", "EUR", "CAD", "JPY"})
        assert p.events(now) == []
        assert p.status.available is False
        assert "COVERAGE_MISSING" in (p.status.error or "")


def test_currency_event_maps_to_relevant_symbols():
    with TemporaryDirectory() as d:
        now = datetime.now(timezone.utc)
        path = Path(d) / "news.json"
        path.write_text(json.dumps({
            "generated_at_utc": now.isoformat(),
            "valid_until_utc": (now + timedelta(hours=12)).isoformat(),
            "source_name": "trusted",
            "source_url": "https://example.test",
            "coverage_currencies": ["USD", "EUR", "CAD", "JPY"],
            "events": [{"event_id":"U1","starts_at_utc":(now+timedelta(hours=2)).isoformat(),"currencies":["USD"],"impact":"HIGH","title":"USD major"}],
        }))
        p = JsonScheduledNewsProvider(path, strict_freshness=True, min_validity_seconds=3600, strict_provenance=True, required_currencies={"USD", "EUR", "CAD", "JPY"})
        events = p.events(now)
        assert len(events) == 1
        assert events[0].affected_symbols == frozenset({"EURUSD", "USDJPY", "USDCAD", "XAUUSD"})


def test_parse_minimal_bls_ics_and_classify_cpi_high():
    ics = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:abc\nDTSTART:20260911T083000\nSUMMARY:Consumer Price Index for August 2026\nEND:VEVENT\nEND:VCALENDAR\n"""
    rows = parse_bls_ics(ics, source_url="https://www.bls.gov/schedule/news_release/bls.ics")
    assert len(rows) == 1
    assert rows[0].impact == "HIGH"
    assert rows[0].currencies == frozenset({"USD"})
    assert rows[0].starts_at_utc.tzinfo is not None

def test_json_provider_rechecks_required_event_families_each_read(tmp_path):
    import json
    from datetime import datetime, timedelta, timezone
    from atlas.services.news_provider import JsonScheduledNewsProvider
    now=datetime.now(timezone.utc)
    families={
        'USD_FOMC':True,'USD_EMPLOYMENT':True,'USD_CPI':True,'EUR_ECB':True,
        'CAD_BOC':True,'CAD_CPI':True,'CAD_LFS':True,'JPY_BOJ':True,'JPY_CPI':True,'JPY_LFS':True,
    }
    raw={
        'generated_at_utc':now.isoformat(),'valid_until_utc':(now+timedelta(hours=12)).isoformat(),
        'source_name':'official','source_url':'manifest','coverage_currencies':['USD','EUR','CAD','JPY'],
        'coverage_status':'FULL_PRIMARY_BACKBONE','required_event_families':families,'events':[]
    }
    p=tmp_path/'news.json'; p.write_text(json.dumps(raw))
    provider=JsonScheduledNewsProvider(p,strict_freshness=True,strict_provenance=True,
        required_currencies={'USD','EUR','CAD','JPY'},required_event_families=set(families))
    provider.events(now); assert provider.status.available is True
    raw['required_event_families']['CAD_CPI']=False; p.write_text(json.dumps(raw))
    provider.events(now); assert provider.status.available is False
    assert 'EVENT_FAMILIES_MISSING' in (provider.status.error or '')
