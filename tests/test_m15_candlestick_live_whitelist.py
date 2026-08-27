from atlas.agents.m15_candlestick_sr import DEFAULT_WHITELIST, M15CandlestickSRLiveAgent
from atlas.coordination.m15_coordinator import M15Coordinator


def test_whitelist_contains_only_researched_symbols_and_positive_setups():
    assert set(DEFAULT_WHITELIST) == {"EURUSD", "USDJPY", "USDCAD", "XAUUSD"}
    assert all(rule.target_r == 2.0 for rules in DEFAULT_WHITELIST.values() for rule in rules)
    assert any(r.pattern == "MORNING_STAR" and r.zone_timeframe == "H1" for r in DEFAULT_WHITELIST["USDJPY"])
    assert any(r.pattern == "SHOOTING_STAR_PIN" and r.zone_timeframe == "H4" for r in DEFAULT_WHITELIST["XAUUSD"])


def test_rules_are_direction_specific():
    agent = object.__new__(M15CandlestickSRLiveAgent)
    agent.whitelist = DEFAULT_WHITELIST
    long_rules = agent.rules_for("USDJPY", "LONG")
    short_rules = agent.rules_for("USDJPY", "SHORT")
    assert long_rules
    assert not short_rules
    assert all(r.pattern in {"HAMMER_PIN", "BULLISH_ENGULFING", "MORNING_STAR"} for r in long_rules)


def test_candlestick_and_channel_same_bar_count_as_independent_confluence():
    reports = [
        {"agent_id":"M15_CHANNEL","status":"VALID_TRIGGER","data":{
            "direction":"LONG","entry_reference":1.1,"raw_stop_anchor":1.0,"final_stop":0.99,
            "breakout_time":"2026-08-22T12:00:00+00:00","freshness":"VALID","last_reason_code":"CHANNEL_BREAK"
        }},
        {"agent_id":"M15_CANDLESTICK_SR","status":"VALID_TRIGGER","data":{
            "direction":"LONG","entry_reference":1.1,"raw_stop_anchor":1.01,"final_stop":1.0,
            "trigger_time":"2026-08-22T12:00:00+00:00","freshness":"VALID","last_reason_code":"WHITELISTED_CANDLESTICK_AT_MAJOR_SR"
        }},
    ]
    pkg=M15Coordinator().build("EURUSD","LONG",reports,eligible_agents={"M15_CHANNEL","M15_CANDLESTICK_SR"})
    assert pkg.coordination_state == "READY_FOR_SUPERVISOR_REVIEW"
    assert pkg.confluence_count == 2
    assert pkg.confluence_level == "CONFIRMED_BY_SECOND_AGENT"
    assert any(c["agent"] == "M15_CANDLESTICK_SR" or pkg.primary_trigger["agent"] == "M15_CANDLESTICK_SR" for c in pkg.confirmations) or pkg.primary_trigger["agent"] == "M15_CANDLESTICK_SR"
    assert "M15_TWO_AGENT_CONFLUENCE" in pkg.reason_codes
