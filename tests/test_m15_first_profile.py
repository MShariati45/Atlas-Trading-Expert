from atlas.strategy.profile import (
    default_m15_first_profile,
    PATTERN_CHANNEL_BOUNDARY,
    PATTERN_FLAG,
    PATTERN_HS,
    PATTERN_IMPULSE,
    PATTERN_MULTIPLE,
    PATTERN_TRIANGLE,
)
from atlas.strategy.pattern_gate import PatternPolicyGate
from atlas.supervisor.runtime import SupervisorRuntime


def test_watchlist_and_fibonacci_disabled():
    p = default_m15_first_profile()
    assert p.watchlist == ("EURUSD", "USDJPY", "USDCAD", "XAUUSD")
    assert p.fibonacci_enabled is False
    assert p.fibonacci_visible is False
    assert p.universal_h1_alignment_required is False
    assert p.max_daily_risk_pct == 1.0
    assert p.risk_per_trade_pct == 0.5
    assert p.max_trades_per_day == 2
    assert p.max_trades_per_symbol_per_day == 1


def test_symbol_pattern_switches():
    p = default_m15_first_profile()
    assert not p.pattern_rule("EURUSD", PATTERN_CHANNEL_BOUNDARY).enabled
    assert not p.pattern_rule("EURUSD", PATTERN_HS).enabled
    assert p.pattern_rule("EURUSD", PATTERN_IMPULSE).enabled
    assert p.pattern_rule("EURUSD", PATTERN_TRIANGLE).enabled
    assert not p.pattern_rule("EURUSD", PATTERN_FLAG).enabled
    assert not p.pattern_rule("EURUSD", PATTERN_MULTIPLE).enabled

    assert p.pattern_rule("USDJPY", PATTERN_CHANNEL_BOUNDARY).enabled
    assert p.pattern_rule("USDJPY", PATTERN_FLAG).enabled
    assert p.pattern_rule("USDJPY", PATTERN_HS).enabled
    assert p.pattern_rule("USDJPY", PATTERN_TRIANGLE).enabled
    assert not p.pattern_rule("USDJPY", PATTERN_IMPULSE).enabled
    assert not p.pattern_rule("USDJPY", PATTERN_MULTIPLE).enabled

    assert not p.pattern_rule("USDCAD", PATTERN_FLAG).enabled
    assert not p.pattern_rule("USDCAD", PATTERN_HS).enabled
    assert not p.pattern_rule("USDCAD", PATTERN_IMPULSE).enabled
    assert p.pattern_rule("USDCAD", PATTERN_MULTIPLE).enabled
    assert p.pattern_rule("USDCAD", PATTERN_TRIANGLE).enabled
    assert p.pattern_rule("USDCAD", PATTERN_CHANNEL_BOUNDARY).enabled

    enabled_gold = p.symbol_profile("XAUUSD").enabled_patterns()
    for name in (PATTERN_CHANNEL_BOUNDARY, PATTERN_FLAG, PATTERN_HS, PATTERN_IMPULSE, PATTERN_MULTIPLE, PATTERN_TRIANGLE):
        assert name in enabled_gold


def test_pattern_specific_htf_rules():
    p = default_m15_first_profile(); g = PatternPolicyGate(p)
    # EURUSD continuation/reversal candidates prefer H4 agreement with H1 correction.
    assert g.evaluate(symbol="EURUSD", pattern=PATTERN_IMPULSE, direction="LONG", h4_trend="BULLISH", h1_trend="BEARISH").allowed
    assert not g.evaluate(symbol="EURUSD", pattern=PATTERN_IMPULSE, direction="LONG", h4_trend="BULLISH", h1_trend="BULLISH").allowed
    # USDCAD boundary channel prefers both higher timeframes opposed to the M15 trade.
    d = g.evaluate(symbol="USDCAD", pattern=PATTERN_CHANNEL_BOUNDARY, direction="LONG", h4_trend="BEARISH", h1_trend="BEARISH")
    assert d.allowed and d.target_r == 3.0
    # Gold original profitable families use H4 only; H1 is advisory.
    assert g.evaluate(symbol="XAUUSD", pattern=PATTERN_FLAG, direction="LONG", h4_trend="BULLISH", h1_trend="BEARISH").allowed
    # USDJPY channel has no hard HTF gate; continuation families use both-aligned context.
    assert g.evaluate(symbol="USDJPY", pattern=PATTERN_CHANNEL_BOUNDARY, direction="LONG", h4_trend="BEARISH", h1_trend="BULLISH").allowed
    assert g.evaluate(symbol="USDJPY", pattern=PATTERN_FLAG, direction="LONG", h4_trend="BULLISH", h1_trend="BULLISH").allowed
    assert not g.evaluate(symbol="USDJPY", pattern=PATTERN_FLAG, direction="LONG", h4_trend="BULLISH", h1_trend="BEARISH").allowed
    assert g.evaluate(symbol="USDJPY", pattern=PATTERN_HS, direction="LONG", h4_trend="BEARISH", h1_trend="BEARISH").allowed



def test_disabled_pair_pattern_combinations_are_rejected():
    p = default_m15_first_profile(); g = PatternPolicyGate(p)
    for symbol, pattern in (
        ("EURUSD", PATTERN_CHANNEL_BOUNDARY),
        ("EURUSD", PATTERN_HS),
        ("EURUSD", PATTERN_FLAG),
        ("EURUSD", PATTERN_MULTIPLE),
        ("USDCAD", PATTERN_FLAG),
        ("USDCAD", PATTERN_HS),
        ("USDCAD", PATTERN_IMPULSE),
        ("USDJPY", PATTERN_IMPULSE),
        ("USDJPY", PATTERN_MULTIPLE),
    ):
        d = g.evaluate(symbol=symbol, pattern=pattern, direction="LONG", h4_trend="BULLISH", h1_trend="BEARISH")
        assert not d.allowed

def test_daily_search_lock_and_one_symbol_per_day():
    p = default_m15_first_profile(); s = SupervisorRuntime.from_strategy_profile(p)
    ok, _ = s.entry_search_allowed("EURUSD"); assert ok
    s.mark_trade_opened("EURUSD", 0.5)
    ok, reasons = s.entry_search_allowed("EURUSD")
    assert not ok and "SYMBOL_ALREADY_TRADED_TODAY_SEARCH_DISABLED" in reasons
    ok, _ = s.entry_search_allowed("USDJPY"); assert ok
    s.mark_trade_opened("USDJPY", 0.5)
    ok, reasons = s.entry_search_allowed("USDCAD")
    assert not ok
    assert "MAX_DAILY_TRADES_REACHED_SEARCH_DISABLED" in reasons
    assert "MAX_DAILY_RISK_REACHED_SEARCH_DISABLED" in reasons


def test_original_channel_breakout_pattern_is_absent_from_registry():
    from atlas.strategy.profile import ALL_PATTERNS
    assert "CHANNEL_BREAKOUT" not in ALL_PATTERNS
