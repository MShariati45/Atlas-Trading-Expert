from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from atlas.market_data.m15_live_runtime import M15LiveSpecialistRuntime
from atlas.market_data.mt5_feed import Candle, SymbolSnapshot
from atlas.core.state_store import JsonFileStateStore

class Feed:
    def __init__(self):
        t=datetime(2026,1,1,tzinfo=timezone.utc); self.b=[]
        # oscillating rising structure gives confirmed swings and enough history
        price=1.10
        for i in range(80):
            wave=(i%6)
            delta=[0.0002,0.0006,0.0009,0.0004,-0.0002,-0.0005][wave]
            c=price+delta; hi=max(price,c)+0.0003; lo=min(price,c)-0.0003
            self.b.append(Candle(t+timedelta(minutes=15*i),price,hi,lo,c,100,2,0)); price=c
    def closed_bars(self,symbol,timeframe,count=300): return self.b[-count:]
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,0.00001,5,0.00001,1,0.01,100,0.01,0,0,True)

def test_m15_runtime_seeds_all_six_and_is_read_only_state_pipeline():
    with TemporaryDirectory() as d:
        rt=M15LiveSpecialistRuntime(Feed(),JsonFileStateStore(Path(d)/'s.json'))
        s=rt.poll('EURUSD','LONG',45.0)
        assert len(s.reports)==6
        assert {r['agent_id'] for r in s.reports}=={'M15_IMPULSE_CORRECTION','M15_MULTIPLE_TOP_BOTTOM','M15_FLAG_PENNANT','M15_TRIANGLE_WEDGE','M15_HEAD_SHOULDERS','M15_CHANNEL'}
        assert s.coordinator['symbol']=='EURUSD'

def test_fib_handoff_disables_new_flag_and_activates_broad_layer():
    with TemporaryDirectory() as d:
        rt=M15LiveSpecialistRuntime(Feed(),JsonFileStateStore(Path(d)/'s.json'))
        s=rt.poll('EURUSD','LONG',45.0)
        by={r['agent_id']:r for r in s.reports}
        assert by['M15_FLAG_PENNANT']['data']['discovery_allowed'] is False
        assert by['M15_TRIANGLE_WEDGE']['data']['fib_retracement_pct']==45.0

def test_latched_recovery_keeps_broad_layer_active_below_38_2_and_flag_discovery_off():
    with TemporaryDirectory() as d:
        rt=M15LiveSpecialistRuntime(Feed(),JsonFileStateStore(Path(d)/'s.json'))
        s=rt.poll(
            'EURUSD','LONG',25.0,
            broad_m15_activation=True,
            new_flag_discovery_allowed=False,
        )
        by={r['agent_id']:r for r in s.reports}
        assert s.broad_m15_activation is True
        assert s.new_flag_discovery_allowed is False
        assert by['M15_FLAG_PENNANT']['data']['discovery_allowed'] is False
        assert by['M15_TRIANGLE_WEDGE']['data']['pattern_state'] != 'INACTIVE'
        assert by['M15_HEAD_SHOULDERS']['data']['pattern_state'] != 'INACTIVE'
        assert by['M15_CHANNEL']['data']['pattern_state'] != 'INACTIVE'


def test_shallow_flag_only_phase_excludes_broad_specialists_from_coordinator():
    with TemporaryDirectory() as d:
        rt=M15LiveSpecialistRuntime(Feed(),JsonFileStateStore(Path(d)/'s.json'))
        s=rt.poll(
            'EURUSD','LONG',20.0,
            broad_m15_activation=False,
            new_flag_discovery_allowed=True,
        )
        assert s.broad_m15_activation is False
        assert s.new_flag_discovery_allowed is True
        # All six states remain visible for audit, but only Flag/Pennant is eligible.
        assert len(s.reports) == 6
        assert s.coordinator['primary_trigger'] is None or s.coordinator['primary_trigger']['agent'] == 'M15_FLAG_PENNANT'


def test_structure_risk_blocks_all_m15_specialists_at_coordinator():
    with TemporaryDirectory() as d:
        rt=M15LiveSpecialistRuntime(Feed(),JsonFileStateStore(Path(d)/'s.json'))
        s=rt.poll(
            'EURUSD','LONG',82.0,
            broad_m15_activation=False,
            new_flag_discovery_allowed=False,
            structure_risk=True,
        )
        assert s.coordinator['coordination_state'] == 'SLEEPING'
        assert s.coordinator['reason_codes'] == ['M15_BLOCKED_BY_H1_STRUCTURE_RISK']
