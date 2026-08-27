from datetime import datetime, timedelta, timezone

from atlas.market_data.mt5_feed import Candle
from atlas.research.candlestick_challenger import (
    RecentImpulseDirectionEngine,
    detect_patterns,
    evaluate_outcome,
    TradeCandidate,
)


def c(i, o, h, l, cl, spread=10):
    return Candle(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=15*i), o,h,l,cl,100,spread,0)


def test_bullish_engulfing_detected():
    bars=[c(0,1.10,1.11,1.08,1.09), c(1,1.085,1.115,1.08,1.112)]
    pats=detect_patterns(bars,1,0.03)
    assert any(p.pattern=="BULLISH_ENGULFING" and p.direction=="LONG" for p in pats)


def test_bearish_engulfing_detected():
    bars=[c(0,1.09,1.11,1.08,1.105), c(1,1.11,1.115,1.075,1.08)]
    pats=detect_patterns(bars,1,0.03)
    assert any(p.pattern=="BEARISH_ENGULFING" and p.direction=="SHORT" for p in pats)


def test_hammer_detected():
    bars=[c(0,1.008,1.021,0.95,1.019)]
    pats=detect_patterns(bars,0,0.05)
    assert any(p.pattern=="HAMMER_PIN" for p in pats)


def test_morning_star_detected_without_gap_requirement():
    bars=[
        c(0,1.10,1.101,1.07,1.075),
        c(1,1.076,1.081,1.068,1.078),
        c(2,1.077,1.103,1.075,1.099),
    ]
    pats=detect_patterns(bars,2,0.04)
    assert any(p.pattern=="MORNING_STAR" for p in pats)


def test_outcome_same_bar_ambiguity_is_loss():
    bars=[c(0,1.0,1.01,0.99,1.0), c(1,1.0,1.25,0.85,1.1)]
    trade=TradeCandidate(
        symbol="EURUSD", signal_time=bars[0].time_utc.isoformat(), pattern="X", direction="LONG",
        h4_state="BULLISH", h4_confidence=.8, zone_timeframe="H4", zone_kind="SUPPORT",
        zone_low=.9, zone_high=1.0, zone_strength=.8, counter_move=True, entry_model="EARLY",
        entry_time=bars[0].time_utc.isoformat(), entry=1.0, stop=.9, risk=.1, atr=.05,
        pattern_low=.95, pattern_high=1.01,
    )
    out=evaluate_outcome(bars,0,trade,2.0)
    assert out.outcome=="LOSS"
    assert out.realized_r==-1.0


def test_recent_impulse_direction_can_classify_bullish():
    # Construct a broad synthetic rising structure with clear local swing highs/lows.
    bars=[]
    price=1.0
    values=[]
    for base in [1.00,1.08,1.03,1.13,1.07,1.18,1.12,1.23,1.17,1.28]:
        values.extend([base, base+0.01, base+0.005])
    for i,v in enumerate(values):
        bars.append(Candle(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(hours=4*i), v, v+0.006, v-0.006, v+0.002,100,5,0))
    result=RecentImpulseDirectionEngine(lookback_bars=180).classify(bars)
    assert result.state in {"BULLISH","TRANSITION"}
