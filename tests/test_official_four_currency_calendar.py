from datetime import datetime, timezone
from atlas.services.official_four_currency_calendar import official_policy_events_2026, japan_macro_events_2026, parse_statcan_high_impact_schedule
from atlas.services.news_guard import NewsGuard, NewsEvent


def test_policy_backbone_has_all_four_currencies():
    rows=official_policy_events_2026()
    assert {c for e in rows for c in e.currencies} == {'USD','EUR','CAD','JPY'}
    assert any(e.title.startswith('FOMC') for e in rows)
    assert any('ECB' in e.title for e in rows)
    assert any('Bank of Canada' in e.title for e in rows)
    assert any('Bank of Japan' in e.title for e in rows)


def test_japan_macro_has_cpi_and_lfs():
    rows=japan_macro_events_2026()
    assert any('Consumer Price Index' in e.title for e in rows)
    assert any('Labour Force Survey' in e.title for e in rows)
    assert all(e.currencies == frozenset({'JPY'}) for e in rows)


def test_statcan_parser_only_promotes_cpi_and_lfs():
    h='''<h3>September 4</h3><p>Labour Force Survey, August 2026</p><p>Other release</p><h3>September 15</h3><p>Consumer Price Index, August 2026</p>'''
    rows=parse_statcan_high_impact_schedule(h)
    assert len(rows)==2
    assert {e.currencies for e in rows} == {frozenset({'CAD'})}


def test_event_specific_post_blackout_is_enforced():
    t=datetime(2026,9,18,3,0,tzinfo=timezone.utc)
    e=NewsEvent('BOJ',t,frozenset({'USDJPY'}),blackout_before_minutes=240,blackout_after_minutes=240)
    g=NewsGuard(); g.set_events([e])
    assert g.assess('USDJPY', datetime(2026,9,18,5,0,tzinfo=timezone.utc)).clear_for_new_entry is False


def test_canada_macro_has_cpi_and_lfs():
    from atlas.services.official_four_currency_calendar import canada_macro_events_2026
    rows=canada_macro_events_2026()
    assert any('Consumer Price Index' in e.title for e in rows)
    assert any('Labour Force Survey' in e.title for e in rows)
    assert all(e.currencies == frozenset({'CAD'}) for e in rows)
    assert len(rows) == 8


def test_required_family_coverage_rejects_rate_only_cad():
    from atlas.services.official_four_currency_calendar import required_family_coverage
    rows=official_policy_events_2026() + japan_macro_events_2026()
    coverage=required_family_coverage(rows)
    assert coverage['CAD_BOC'] is True
    assert coverage['CAD_CPI'] is False
    assert coverage['CAD_LFS'] is False


def test_required_family_coverage_passes_with_canada_macro_and_bls():
    from atlas.services.official_four_currency_calendar import canada_macro_events_2026, required_family_coverage
    from atlas.services.official_calendar import OfficialCalendarEvent
    rows=official_policy_events_2026() + japan_macro_events_2026() + canada_macro_events_2026()
    rows += [
        OfficialCalendarEvent('BLS:EMP', datetime(2026,9,4,12,30,tzinfo=timezone.utc), 'Employment Situation', frozenset({'USD'}), 'HIGH', 'BLS', 'https://bls.gov'),
        OfficialCalendarEvent('BLS:CPI', datetime(2026,9,11,12,30,tzinfo=timezone.utc), 'Consumer Price Index', frozenset({'USD'}), 'HIGH', 'BLS', 'https://bls.gov'),
    ]
    assert all(required_family_coverage(rows).values())
