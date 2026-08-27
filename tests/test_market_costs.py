from atlas.services.market_costs import MarketCostService

def test_costs_can_reject_theoretical_two_r():
    a = MarketCostService().assess(
        entry=1.1000, stop=1.0990, target=1.1020, point_size=0.0001,
        spread_points=2, expected_slippage_points=1,
        max_spread_points=3, max_slippage_points=2, min_net_rr=2.0,
    )
    assert a.spread_ok and a.slippage_ok
    assert not a.net_rr_ok
    assert a.net_rr < 2.0

def test_excessive_spread_fails_gate():
    a = MarketCostService().assess(
        entry=100, stop=99, target=102.5, point_size=0.1,
        spread_points=5, expected_slippage_points=0,
        max_spread_points=3, max_slippage_points=2, min_net_rr=1.5,
    )
    assert not a.spread_ok
