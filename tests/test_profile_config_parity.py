import json
from pathlib import Path
from atlas.strategy.profile import default_m15_first_profile


def test_v0235_json_matches_runtime_profile_permissions_and_targets():
    cfg=json.loads(Path('config/atlas_m15_first_v0.24.4.json').read_text())
    p=default_m15_first_profile()
    assert tuple(cfg['watchlist']) == p.watchlist
    assert cfg['risk']['max_daily_risk_pct'] == p.max_daily_risk_pct
    assert cfg['risk']['risk_per_trade_pct'] == p.risk_per_trade_pct
    assert cfg['risk']['max_trades_per_day'] == p.max_trades_per_day
    assert cfg['risk']['max_trades_per_symbol_per_day'] == p.max_trades_per_symbol_per_day
    for symbol in p.watchlist:
        sp=p.symbol_profile(symbol)
        assert set(cfg['symbols'][symbol]) == set(sp.patterns)
        for pattern, rule in sp.patterns.items():
            row=cfg['symbols'][symbol][pattern]
            assert bool(row['enabled']) == rule.enabled
            assert float(row.get('target_r', 2.0)) == rule.target_r
            assert row.get('htf_mode', 'ANY') == rule.htf_mode


def test_ai_usage_is_disabled_in_demo_config():
    cfg=json.loads(Path('config/atlas_m15_first_v0.24.4.json').read_text())
    assert cfg['ai_usage']['enabled'] is False
    assert cfg['ai_usage']['mode'] == 'EVENT_DRIVEN_ONLY'
