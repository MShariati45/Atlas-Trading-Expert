from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from atlas.core.events import Event
from atlas.core.state_store import InMemoryStateStore
from atlas.market_data.m15_live_runtime import M15LiveSpecialistRuntime
from atlas.market_data.mt5_feed import Candle, SymbolSnapshot


class Feed:
    def ensure_symbol(self, symbol):
        return SymbolSnapshot(symbol, 0.00001, 5, 0.00001, 1.0, 0.01, 100.0, 0.01, 0, 0, True)


def _bar(t, o, h, l, c):
    return Candle(t, o, h, l, c, 100, 8, 0)


def test_flag_discovery_excludes_current_breakout_bar_from_consolidation():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Six-bar bullish pole, four shallow consolidation bars, then breakout.
    vals = [
        (1.0998,1.1001,1.0997,1.1000),
        (1.1000,1.1007,1.0999,1.1006),
        (1.1006,1.1013,1.1005,1.1012),
        (1.1012,1.1019,1.1011,1.1018),
        (1.1018,1.1025,1.1017,1.1024),
        (1.1024,1.1031,1.1023,1.1030),
        (1.1030,1.1037,1.1029,1.1036),
        (1.1036,1.1038,1.1032,1.1034),
        (1.1034,1.1037,1.1031,1.1033),
        (1.1033,1.1036,1.1030,1.1032),
        (1.1032,1.1037,1.1031,1.1035),
        (1.1035,1.1043,1.1034,1.1042),
    ]
    bars=[_bar(t+timedelta(minutes=15*i),*v) for i,v in enumerate(vals)]
    store=InMemoryStateStore(); rt=M15LiveSpecialistRuntime(Feed(),store)
    rt.flag.seed('EURUSD', permitted_direction='LONG', fib_retracement_pct=20.0)
    rt._discover_candidates('EURUSD','LONG',20.0,bars,broad_active=False,new_flag_discovery_allowed=True)
    before=store.get(rt.flag._key('EURUSD'))
    assert before['pattern_state']=='MATURE'
    assert before['breakout_level'] < bars[-1].close
    payload=rt._enriched('EURUSD',bars[-1],bars)
    rep=rt.flag.handle(Event('M15_BAR_CLOSED',symbol='EURUSD',timeframe='M15',payload=payload))
    assert rep is not None
    assert rep.status=='VALID_TRIGGER'


def test_triangle_discovery_uses_nearest_structural_obstacle_beyond_boundary():
    t=datetime(2026,1,1,tzinfo=timezone.utc)
    bars=[_bar(t+timedelta(minutes=15*i),1.1000,1.1005,1.0995,1.1000) for i in range(20)]
    swings=[
        SimpleNamespace(kind='HIGH',price=1.1050,time=t,index=0),
        SimpleNamespace(kind='LOW',price=1.0930,time=t,index=1),
        SimpleNamespace(kind='HIGH',price=1.1020,time=t,index=2),
        SimpleNamespace(kind='LOW',price=1.0940,time=t,index=3),
        SimpleNamespace(kind='HIGH',price=1.1010,time=t,index=4),
        SimpleNamespace(kind='LOW',price=1.0950,time=t,index=5),
        SimpleNamespace(kind='HIGH',price=1.1005,time=t,index=6),
        SimpleNamespace(kind='LOW',price=1.0955,time=t,index=7),
        SimpleNamespace(kind='HIGH',price=1.1000,time=t,index=8),
        SimpleNamespace(kind='LOW',price=1.0960,time=t,index=9),
        SimpleNamespace(kind='HIGH',price=1.0990,time=t,index=10),
        SimpleNamespace(kind='LOW',price=1.0970,time=t,index=11),
    ]
    store=InMemoryStateStore(); rt=M15LiveSpecialistRuntime(Feed(),store)
    rt.triangle.seed('EURUSD', permitted_direction='LONG', fib_retracement_pct=45.0)
    rt.bootstrapper.swings=lambda _bars: swings
    rt._discover_candidates('EURUSD','LONG',45.0,bars,broad_active=True,new_flag_discovery_allowed=False)
    state=store.get(rt.triangle._key('EURUSD'))
    assert state['pattern_state']=='MATURE'
    # Upper boundary is mean(1.1000, 1.0990)=1.0995; nearest old high above it is 1.1020.
    assert abs(state['first_structural_sr']-1.1020) < 1e-12


def test_pennant_discovery_classifies_converging_consolidation():
    t=datetime(2026,2,1,tzinfo=timezone.utc)
    vals=[
        (1.0996,1.1001,1.0995,1.1000),
        (1.1000,1.1005,1.0999,1.1004),(1.1004,1.1010,1.1003,1.1009),
        (1.1009,1.1015,1.1008,1.1014),(1.1014,1.1020,1.1013,1.1019),
        (1.1019,1.1025,1.1018,1.1024),(1.1024,1.1030,1.1023,1.1029),
        # frozen four-bar converging consolidation
        (1.1029,1.1032,1.1024,1.1028),(1.1028,1.1031,1.1025,1.1029),
        (1.1029,1.1030,1.1026,1.1028),(1.1028,1.10295,1.10265,1.10285),
        (1.10285,1.1034,1.1028,1.1033),
    ]
    bars=[_bar(t+timedelta(minutes=15*i),*v) for i,v in enumerate(vals)]
    store=InMemoryStateStore(); rt=M15LiveSpecialistRuntime(Feed(),store)
    rt.flag.seed('EURUSD', permitted_direction='LONG', fib_retracement_pct=20.0)
    rt._discover_candidates('EURUSD','LONG',20.0,bars,broad_active=False,new_flag_discovery_allowed=True)
    state=store.get(rt.flag._key('EURUSD'))
    assert state['pattern_state']=='MATURE'
    assert state['pattern_type']=='BULL_PENNANT'


def test_triangle_wedge_discovery_classifies_supported_geometries():
    t=datetime(2026,3,1,tzinfo=timezone.utc)
    bars=[_bar(t+timedelta(minutes=15*i),1.1000,1.1005,1.0995,1.1000) for i in range(30)]
    cases=[
        ('LONG', 1.1000,1.10001, 1.0960,1.0980, 'ASCENDING_TRIANGLE'),
        ('SHORT',1.1020,1.1000, 1.0980,1.09799, 'DESCENDING_TRIANGLE'),
        ('SHORT',1.1000,1.1010, 1.0960,1.0980, 'RISING_WEDGE'),
        ('LONG', 1.1020,1.1000, 1.0980,1.0970, 'FALLING_WEDGE'),
    ]
    for direction,h1,h2,l1,l2,expected in cases:
        # external obstacles first, then eight formation swings
        swings=[
            SimpleNamespace(kind='HIGH',price=1.1060,time=t,index=0),
            SimpleNamespace(kind='LOW',price=1.0920,time=t,index=1),
            SimpleNamespace(kind='HIGH',price=h1,time=t,index=2),
            SimpleNamespace(kind='LOW',price=l1,time=t,index=3),
            SimpleNamespace(kind='HIGH',price=(h1+h2)/2,time=t,index=4),
            SimpleNamespace(kind='LOW',price=(l1+l2)/2,time=t,index=5),
            SimpleNamespace(kind='HIGH',price=h1,time=t,index=6),
            SimpleNamespace(kind='LOW',price=l1,time=t,index=7),
            SimpleNamespace(kind='HIGH',price=h2,time=t,index=8),
            SimpleNamespace(kind='LOW',price=l2,time=t,index=9),
        ]
        store=InMemoryStateStore(); rt=M15LiveSpecialistRuntime(Feed(),store)
        rt.triangle.seed('EURUSD', permitted_direction=direction, fib_retracement_pct=45.0)
        rt.bootstrapper.swings=lambda _bars, ss=swings: ss
        rt._discover_candidates('EURUSD',direction,45.0,bars,broad_active=True,new_flag_discovery_allowed=False)
        state=store.get(rt.triangle._key('EURUSD'))
        assert state['pattern_state']=='MATURE', (expected,state)
        assert state['pattern_type']==expected, (expected,state['pattern_type'])


def test_live_discovery_does_not_overwrite_fresh_flag_trigger():
    t=datetime(2026,4,1,tzinfo=timezone.utc)
    bars=[_bar(t+timedelta(minutes=15*i),1.1000,1.1005,1.0995,1.1000) for i in range(20)]
    store=InMemoryStateStore(); rt=M15LiveSpecialistRuntime(Feed(),store)
    rt.flag.seed('EURUSD', permitted_direction='LONG', fib_retracement_pct=20.0)
    raw=store.get(rt.flag._key('EURUSD')); raw.update({'pattern_state':'VALID_TRIGGER','breakout_time':'2026-04-01T01:00:00+00:00','entry_reference':1.1010,'bars_since_trigger':0})
    store.set(rt.flag._key('EURUSD'),raw)
    rt._discover_candidates('EURUSD','LONG',20.0,bars,broad_active=False,new_flag_discovery_allowed=True)
    after=store.get(rt.flag._key('EURUSD'))
    assert after['pattern_state']=='VALID_TRIGGER'
    assert after['breakout_time']=='2026-04-01T01:00:00+00:00'


def test_live_discovery_does_not_overwrite_fresh_triangle_wedge_trigger():
    t=datetime(2026,4,2,tzinfo=timezone.utc)
    bars=[_bar(t+timedelta(minutes=15*i),1.1000,1.1005,1.0995,1.1000) for i in range(20)]
    store=InMemoryStateStore(); rt=M15LiveSpecialistRuntime(Feed(),store)
    rt.triangle.seed('EURUSD', permitted_direction='LONG', fib_retracement_pct=45.0)
    raw=store.get(rt.triangle._key('EURUSD')); raw.update({'pattern_state':'VALID_TRIGGER','pattern_type':'FALLING_WEDGE','structural_break_time':'2026-04-02T01:00:00+00:00','entry_reference':1.1010,'bars_since_trigger':0})
    store.set(rt.triangle._key('EURUSD'),raw)
    rt._discover_candidates('EURUSD','LONG',45.0,bars,broad_active=True,new_flag_discovery_allowed=False)
    after=store.get(rt.triangle._key('EURUSD'))
    assert after['pattern_state']=='VALID_TRIGGER'
    assert after['pattern_type']=='FALLING_WEDGE'
    assert after['structural_break_time']=='2026-04-02T01:00:00+00:00'
