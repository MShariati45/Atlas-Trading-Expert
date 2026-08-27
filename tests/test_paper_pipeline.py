from datetime import datetime, timezone
from atlas.market_data.mt5_feed import Candle, SymbolSnapshot, TickSnapshot
from atlas.services.paper_pipeline import LivePaperSupervisorPipeline

class Feed:
    def closed_bars(self,symbol,timeframe,count=300):
        # Not used when zone builder is replaced.
        return []
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,0.0001,4,0.0001,1,0.01,100,0.01,0,0,True)
    def tick(self,symbol): return TickSnapshot(symbol,datetime.now(timezone.utc),1.1000,1.1001,1.10005,0.0)

class ZoneAssessment:
    clear_for_target=False; blocking_zone=None; nearest_support=None; nearest_resistance=None; reason_codes=['STATIC_ZONE_BLOCKED']
class ZoneSvc:
    def assess_target_path(self,*a,**k): return ZoneAssessment()
class ZoneBuilder:
    def build(self,symbol): return ZoneSvc()


def test_paper_supervisor_blocks_when_static_zone_blocks_and_news_missing():
    p=LivePaperSupervisorPipeline(Feed(),None,zone_builder=ZoneBuilder(),market_limits_by_symbol={'EURUSD':{'max_spread_points':3.0,'expected_slippage_points':0.0,'max_slippage_points':2.0}})
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.decision in {'REJECT','WAIT'}
    assert r.gates['static_zone_ok'] is False
    assert r.gates['news_ok'] is None

class ClearZoneAssessment:
    clear_for_target=True; blocking_zone=None; nearest_support=None; nearest_resistance=None; reason_codes=['STATIC_ZONE_CLEAR']
class ClearZoneSvc:
    def assess_target_path(self,*a,**k): return ClearZoneAssessment()
class ClearZoneBuilder:
    def build(self,symbol): return ClearZoneSvc()
class NewsResult:
    gate=True; provider_status={'available':True}; assessment=None; reason_codes=['NEWS_CLEAR']
class ClearNews:
    def assess(self,*a,**k): return NewsResult()


def test_fixed_two_r_is_not_rejected_merely_because_positive_spread_reduces_diagnostic_net_rr():
    p=LivePaperSupervisorPipeline(Feed(),ClearNews(),zone_builder=ClearZoneBuilder(),market_limits_by_symbol={'EURUSD':{'max_spread_points':3.0,'expected_slippage_points':0.0,'max_slippage_points':2.0}})
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.net_rr < 2.0
    assert r.gates['spread_ok'] is True
    assert r.gates['net_rr_ok'] is True
    assert r.decision == 'APPROVE'


def test_explicit_post_cost_rr_floor_can_still_be_enabled_as_policy():
    from atlas.risk.policy import RiskPolicy
    from atlas.supervisor.runtime import SupervisorRuntime
    sup=SupervisorRuntime(RiskPolicy(min_net_rr_after_costs=2.0))
    p=LivePaperSupervisorPipeline(Feed(),ClearNews(),supervisor=sup,zone_builder=ClearZoneBuilder(),market_limits_by_symbol={'EURUSD':{'max_spread_points':3.0,'expected_slippage_points':0.0,'max_slippage_points':2.0}})
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.gates['net_rr_ok'] is False
    assert r.decision == 'REJECT'

def _clear_pipeline():
    return LivePaperSupervisorPipeline(Feed(),ClearNews(),zone_builder=ClearZoneBuilder(),market_limits_by_symbol={'EURUSD':{'max_spread_points':3.0,'expected_slippage_points':0.0,'max_slippage_points':2.0},'XAUUSD':{'max_spread_points':100.0,'expected_slippage_points':0.0,'max_slippage_points':20.0}})


def test_stale_opportunity_package_is_hard_rejected_by_supervisor():
    p=_clear_pipeline()
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'STALE','reason_codes':['TRIGGER_NOT_FRESH'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.gates['freshness_ok'] is False
    assert r.decision == 'REJECT'


def test_missing_structural_stop_is_hard_rejected_by_supervisor():
    p=_clear_pipeline()
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':None}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.gates['structural_stop_ok'] is False
    assert r.decision == 'REJECT'


def test_coordinator_conflict_state_is_hard_rejected_by_supervisor():
    p=_clear_pipeline()
    pkg={'coordination_state':'CONFLICT_REVIEW','freshness':'VALID','reason_codes':['CONFLICTING_EVIDENCE'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.gates['m15_ok'] is False
    assert r.decision == 'REJECT'


def test_paper_pipeline_honors_pattern_specific_three_r_target():
    p=_clear_pipeline()
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'target_r':3.0,'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='XAUUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert round(r.target, 6) == 1.103


def test_missing_broker_cost_calibration_forces_wait_not_approval():
    p=LivePaperSupervisorPipeline(Feed(),ClearNews(),zone_builder=ClearZoneBuilder())
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.gates['spread_ok'] is None
    assert r.gates['net_rr_ok'] is None
    assert r.decision == 'WAIT'
    assert 'MARKET_COST_CALIBRATION_UNAVAILABLE' in r.reason_codes

class ZeroSpreadFeed(Feed):
    def tick(self,symbol): return TickSnapshot(symbol,datetime.now(timezone.utc),1.1000,1.1000,1.1000,0.0)


def test_paper_only_cost_policy_forces_wait_on_nonpositive_spread():
    limits={'EURUSD':{
        'max_spread_points':1.0,
        'reject_nonpositive_spread':True,
        'slippage_validated':False,
        'expected_slippage_points':0.0,
        'max_slippage_points':0.0,
        'cost_basis':'SPREAD_ONLY',
    }}
    p=LivePaperSupervisorPipeline(ZeroSpreadFeed(),ClearNews(),zone_builder=ClearZoneBuilder(),market_limits_by_symbol=limits)
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.decision == 'WAIT'
    assert r.gates['spread_ok'] is None
    assert 'NONPOSITIVE_SPREAD_UNVERIFIED' in r.reason_codes
    assert r.market_costs['status'] == 'WAIT_NONPOSITIVE_SPREAD'


def test_paper_only_cost_policy_can_approve_with_spread_only_and_marks_slippage_unmeasured():
    limits={'EURUSD':{
        'max_spread_points':1.0,
        'reject_nonpositive_spread':True,
        'slippage_validated':False,
        'expected_slippage_points':0.0,
        'max_slippage_points':0.0,
        'cost_basis':'SPREAD_ONLY',
    }}
    p=LivePaperSupervisorPipeline(Feed(),ClearNews(),zone_builder=ClearZoneBuilder(),market_limits_by_symbol=limits)
    pkg={'coordination_state':'READY_FOR_SUPERVISOR_REVIEW','freshness':'VALID','reason_codes':['M15_PACKAGE_READY'],
         'primary_trigger':{'entry_reference':1.1000,'final_stop':1.0990}}
    r=p.review(symbol='EURUSD',direction='LONG',package=pkg,alignment_ok=True,fib_ok=True,now=datetime(2026,8,18,18,0,tzinfo=timezone.utc))
    assert r.decision == 'APPROVE'
    assert r.gates['spread_ok'] is True
    assert r.market_costs['status'] == 'PAPER_SPREAD_ONLY'
    assert r.market_costs['slippage_validated'] is False
    assert 'PAPER_COST_SPREAD_ONLY_SLIPPAGE_UNMEASURED' in r.reason_codes
