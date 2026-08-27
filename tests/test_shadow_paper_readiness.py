import json
from pathlib import Path

from atlas.services.broker_cost_policy import load_broker_cost_policy, PAPER_ONLY, EXECUTION_VALIDATED
from run_shadow_paper_supervisor import _news_file_family_ok, REQUIRED_NEWS_FAMILIES

SYMBOLS=("EURUSD","USDJPY","USDCAD","XAUUSD")


def test_missing_cost_policy_is_not_approved(tmp_path):
    s=load_broker_cost_policy(tmp_path/'missing.json', SYMBOLS)
    assert s.approved is False
    assert 'BROKER_COST_POLICY_MISSING' in s.reason_codes


def test_cost_policy_requires_explicit_approval(tmp_path):
    p=tmp_path/'cost.json'
    p.write_text(json.dumps({'approved':False,'mode':'PAPER_ONLY','symbols':{}}))
    s=load_broker_cost_policy(p, SYMBOLS)
    assert s.approved is False
    assert s.reason_codes == ('BROKER_COST_POLICY_NOT_APPROVED',)


def test_paper_only_policy_requires_all_symbols_but_not_fake_slippage(tmp_path):
    rows={s:{'max_spread_points':3,'reject_nonpositive_spread':True} for s in SYMBOLS}
    p=tmp_path/'cost.json'; p.write_text(json.dumps({'approved':True,'mode':PAPER_ONLY,'execution_validated':False,'symbols':rows}))
    s=load_broker_cost_policy(p, SYMBOLS)
    assert s.approved is True
    assert s.mode == PAPER_ONLY
    assert s.execution_validated is False
    assert set(s.limits_by_symbol)==set(SYMBOLS)
    assert all(row['slippage_validated'] is False for row in s.limits_by_symbol.values())
    assert all(row['cost_basis']=='SPREAD_ONLY' for row in s.limits_by_symbol.values())


def test_execution_validated_mode_requires_explicit_execution_validation(tmp_path):
    rows={s:{'max_spread_points':3,'expected_slippage_points':1,'max_slippage_points':2} for s in SYMBOLS}
    p=tmp_path/'cost.json'; p.write_text(json.dumps({'approved':True,'mode':EXECUTION_VALIDATED,'execution_validated':False,'symbols':rows}))
    s=load_broker_cost_policy(p, SYMBOLS)
    assert s.approved is False
    assert 'EXECUTION_COST_VALIDATION_REQUIRED' in s.reason_codes


def test_execution_validated_policy_requires_sane_slippage(tmp_path):
    rows={s:{'max_spread_points':3,'expected_slippage_points':3,'max_slippage_points':2} for s in SYMBOLS}
    p=tmp_path/'cost.json'; p.write_text(json.dumps({'approved':True,'mode':EXECUTION_VALIDATED,'execution_validated':True,'symbols':rows}))
    s=load_broker_cost_policy(p, SYMBOLS)
    assert s.approved is False
    assert any('RANGE_INVALID' in x for x in s.reason_codes)


def test_news_family_file_requires_all_families(tmp_path):
    p=tmp_path/'news.json'
    p.write_text(json.dumps({'coverage_status':'FULL_PRIMARY_BACKBONE','required_event_families':{x:True for x in REQUIRED_NEWS_FAMILIES}}))
    ok,reasons=_news_file_family_ok(p)
    assert ok is True and reasons == []
    raw=json.loads(p.read_text()); raw['required_event_families']['CAD_CPI']=False; p.write_text(json.dumps(raw))
    ok,reasons=_news_file_family_ok(p)
    assert ok is False
    assert 'NEWS_FAMILY_MISSING:CAD_CPI' in reasons


def test_news_family_file_requires_full_coverage_status(tmp_path):
    p=tmp_path/'news.json'
    p.write_text(json.dumps({'coverage_status':'PARTIAL_EVENT_FAMILY_COVERAGE','required_event_families':{x:True for x in REQUIRED_NEWS_FAMILIES}}))
    ok,reasons=_news_file_family_ok(p)
    assert ok is False
    assert 'NEWS_COVERAGE_STATUS_NOT_FULL' in reasons


def test_packaged_v0244_policy_is_paper_only_and_approved():
    p=Path('config/broker_cost_policy.json')
    s=load_broker_cost_policy(p, SYMBOLS)
    assert s.approved is True
    assert s.mode == PAPER_ONLY
    assert s.execution_validated is False
    assert s.limits_by_symbol['EURUSD']['max_spread_points'] == 1.0
    assert s.limits_by_symbol['USDJPY']['max_spread_points'] == 3.0
    assert s.limits_by_symbol['USDCAD']['max_spread_points'] == 1.0
    assert s.limits_by_symbol['XAUUSD']['max_spread_points'] == 44.0
