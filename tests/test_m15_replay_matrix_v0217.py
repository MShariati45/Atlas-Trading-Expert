from atlas.agents.h4_structure import PricePoint
from atlas.agents.m15_impulse_correction import M15ImpulseCorrectionEngine
from atlas.agents.m15_multiple_top_bottom import MultipleTopBottomEngine, Pivot
from atlas.agents.m15_flag_pennant import M15FlagPennantEngine
from atlas.agents.m15_triangle_wedge import M15TriangleWedgeEngine
from atlas.agents.m15_head_shoulders import M15HeadShouldersEngine, HeadShouldersPolicy
from atlas.agents.m15_channel import M15ChannelEngine, ChannelPolicy
from atlas.coordination.m15_coordinator import M15Coordinator


def market(time='t', close=1.0, high=None, low=None, atr=0.001):
    return {'time':time,'close':close,'high':high if high is not None else close+0.0005,
            'low':low if low is not None else close-0.0005,'atr':atr,'spread':0.00008,
            'wick_stat':0.00030,'tick_size':0.00001}


def pkg(agent,status,data,direction='LONG'):
    p=M15Coordinator().build('EURUSD',direction,[{'agent_id':agent,'status':status,'data':data}])
    return p


def test_impulse_correction_replay_normalizes_to_supervisor_ready():
    e=M15ImpulseCorrectionEngine(); s=e.seed(trend='BEARISH',control_pivot=PricePoint(1.1050,'lh'),endpoint=PricePoint(1.1000,'ll'),permitted_direction='LONG')
    for b in [market('c1',1.1055,1.1060,1.1010),market('c2',1.1075,1.1080,1.1055),market('c3',1.1050,1.1070,1.1045)]: e.update(s,b)
    hh=s.new_extreme.price; e.update(s,market('c4',hh+0.0005,hh+0.0010,1.1050))
    p=pkg('M15_IMPULSE_CORRECTION',s.phase,s.to_dict())
    assert p.coordination_state=='READY_FOR_SUPERVISOR_REVIEW'
    assert p.primary_trigger['raw_stop_anchor'] and p.primary_trigger['final_stop'] < p.primary_trigger['entry_reference']


def test_multiple_bottom_replay_is_early_and_waits_for_structure():
    e=MultipleTopBottomEngine(); s=e.seed(permitted_direction='LONG',prior_trend='BEARISH')
    for pvt in [Pivot('LOW',1.1000,'p1',1),Pivot('HIGH',1.1050,'p2',4),Pivot('LOW',1.1001,'p3',8)]: e.register_pivot(s,pvt,market())
    e.update_bar(s,market('break',1.1052))
    p=pkg('M15_MULTIPLE_TOP_BOTTOM',s.pattern_state,s.to_dict())
    assert p.coordination_state=='WAITING_FOR_CONFIRMATION'
    assert p.primary_trigger['status']=='EARLY_REVERSAL_CANDIDATE'


def test_flag_replay_normalizes_to_supervisor_ready():
    e=M15FlagPennantEngine(); s=e.seed(permitted_direction='LONG',fib_retracement_pct=20)
    e.register_flagpole(s,{'origin':1.1000,'endpoint':1.1040,'bars':4,'atr':0.001})
    e.update_consolidation(s,{'high':1.1035,'low':1.1028,'bars':4,'shape':'FLAG'})
    e.update_bar(s,market('break',1.1037))
    p=pkg('M15_FLAG_PENNANT',s.pattern_state,s.to_dict())
    assert p.coordination_state=='READY_FOR_SUPERVISOR_REVIEW'
    assert p.primary_trigger['pattern_type']=='BULL_FLAG'


def test_triangle_replay_normalizes_to_supervisor_ready():
    e=M15TriangleWedgeEngine(); s=e.seed(permitted_direction='LONG',fib_retracement_pct=50)
    e.register_pattern(s,{'pattern_type':'SYMMETRICAL_TRIANGLE','upper_boundary':1.1050,'lower_boundary':1.1010,'reaction_highs':3,'reaction_lows':3,'first_structural_sr':1.1060,'stop_anchor':1.1020})
    e.update_bar(s,market('both',1.1063))
    p=pkg('M15_TRIANGLE_WEDGE',s.pattern_state,s.to_dict())
    assert p.coordination_state=='READY_FOR_SUPERVISOR_REVIEW'
    assert p.primary_trigger['trigger_time']=='both'


def test_inverse_head_shoulders_replay_normalizes_to_supervisor_ready():
    e=M15HeadShouldersEngine(HeadShouldersPolicy(entry_model='BREAKOUT')); s=e.seed(permitted_direction='LONG',prior_trend='BEARISH',fib_retracement_pct=52)
    e.register_pattern(s,{'pattern_type':'INVERSE_HEAD_SHOULDERS','left_shoulder':1.0920,'head':1.0890,'right_shoulder':1.0923,'neckline':1.0970,'atr':0.001})
    e.update_bar(s,market('break',1.0973))
    p=pkg('M15_HEAD_SHOULDERS',s.pattern_state,s.to_dict())
    assert p.coordination_state=='READY_FOR_SUPERVISOR_REVIEW'
    assert p.primary_trigger['final_stop'] < p.primary_trigger['entry_reference']


def test_channel_replay_normalizes_to_supervisor_ready():
    e=M15ChannelEngine(ChannelPolicy()); s=e.seed(permitted_direction='LONG',fib_retracement_pct=50)
    e.register_pattern(s,{'channel_type':'DESCENDING_CHANNEL','upper_boundary':1.1050,'lower_boundary':1.1010,'reaction_highs':3,'reaction_lows':3,'upper_slope':-0.0002,'lower_slope':-0.00022,'stop_anchor':1.1008})
    e.update_bar(s,{'time':'reject','open':1.1011,'high':1.1016,'low':1.1007,'close':1.1015,'atr':0.001,'spread':0.00008,'wick_stat':0.0003,'tick_size':0.00001})
    p=pkg('M15_CHANNEL',s.pattern_state,s.to_dict())
    assert p.coordination_state=='READY_FOR_SUPERVISOR_REVIEW'
    assert p.primary_trigger['trigger_time']=='reject'
