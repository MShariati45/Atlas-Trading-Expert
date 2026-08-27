from atlas.supervisor.runtime import SupervisorRuntime, SupervisorContext
from atlas.core.enums import Decision, SupervisorMode

def ctx(symbol='EURUSD', risk=.5, **overrides):
    d=dict(symbol=symbol,proposed_risk_pct=risk,day_ok=True,session_ok=True,alignment_ok=True,fib_ok=True,m15_ok=True,freshness_ok=True,static_zone_ok=True,spread_ok=True,news_ok=True,structural_stop_ok=True,net_rr_ok=True)
    d.update(overrides); return SupervisorContext(**d)

def test_runtime_approves_then_trade_focus():
    s=SupervisorRuntime(); r=s.review(ctx()); assert r.result.decision is Decision.APPROVE
    s.mark_trade_opened('EURUSD',.5); assert s.mode is SupervisorMode.TRADE_FOCUS

def test_symbol_locked_after_first_trade_even_after_close():
    s=SupervisorRuntime(); s.mark_trade_opened('EURUSD',.5); s.mark_trade_closed()
    r=s.review(ctx()); assert r.result.decision is Decision.REJECT; assert not r.gates['symbol_lock_ok']

def test_two_trades_lock_day():
    s=SupervisorRuntime(); s.mark_trade_opened('EURUSD',.5); s.mark_trade_closed(); s.mark_trade_opened('USDJPY',.5); s.mark_trade_closed()
    assert s.mode is SupervisorMode.DAILY_LOCKED
    r=s.review(ctx(symbol='USDJPY')); assert r.result.decision is Decision.REJECT; assert not r.gates['daily_trade_limit_ok']; assert not r.gates['daily_risk_ok']

def test_pending_news_means_wait():
    s=SupervisorRuntime(); r=s.review(ctx(news_ok=None)); assert r.result.decision is Decision.WAIT


def test_supervisor_allows_early_h4_bullish_path_when_h1_and_all_gates_align():
    s=SupervisorRuntime()
    r=s.review(ctx(
        alignment_ok=False,  # directional fields take precedence
        h4_strategic_trend="BEARISH",
        h4_early_direction="BULLISH",
        h1_trend="BULLISH",
        requested_direction="LONG",
    ))
    assert r.result.decision is Decision.APPROVE
    assert r.gates["alignment_ok"] is True
    assert "EARLY_H4_REVERSAL_PATH_VALID" in r.reason_codes


def test_supervisor_rejects_early_h4_path_if_h1_has_not_realigned():
    s=SupervisorRuntime()
    r=s.review(ctx(
        h4_strategic_trend="BEARISH",
        h4_early_direction="BULLISH",
        h1_trend="BEARISH",
        requested_direction="LONG",
    ))
    assert r.result.decision is Decision.REJECT
    assert r.gates["alignment_ok"] is False
    assert "H4_H1_EFFECTIVE_DIRECTION_MISMATCH" in r.reason_codes


def test_supervisor_early_path_still_cannot_override_static_zone_gate():
    s=SupervisorRuntime()
    r=s.review(ctx(
        h4_strategic_trend="BEARISH",
        h4_early_direction="BULLISH",
        h1_trend="BULLISH",
        requested_direction="LONG",
        static_zone_ok=False,
    ))
    assert r.result.decision is Decision.REJECT
    assert "EARLY_H4_REVERSAL_PATH_VALID" in r.reason_codes
    assert "GATE_FAILED:static_zone_ok" in r.reason_codes
