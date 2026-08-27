from atlas.agents.fibonacci import FibonacciRetracementEngine


def test_shallow_correction_only_flag_has_early_access():
    e = FibonacciRetracementEngine()
    s = e.calculate(direction="BULLISH", origin=100, endpoint=120, current=116, aligned=True)
    assert 0 < s.retracement_pct < 38.2
    assert s.flag_early_access is True
    assert s.broad_m15_activation is False
    assert s.new_flag_discovery_allowed is True


def test_38_2_plus_activates_broad_m15_and_stops_new_flag_discovery():
    e = FibonacciRetracementEngine()
    s = e.calculate(direction="BULLISH", origin=100, endpoint=120, current=112, aligned=True)
    assert s.retracement_pct >= 38.2
    assert s.broad_m15_activation is True
    assert s.new_flag_discovery_allowed is False


def test_deep_correction_is_structure_risk_at_78_6_plus():
    e = FibonacciRetracementEngine()
    s = e.calculate(direction="BULLISH", origin=100, endpoint=120, current=104, aligned=True)
    assert s.retracement_pct >= 78.6
    assert s.state == "STRUCTURE_RISK"


def test_no_alignment_means_fibonacci_inactive():
    e = FibonacciRetracementEngine()
    s = e.calculate(direction="BULLISH", origin=100, endpoint=120, current=114, aligned=False)
    assert s.state == "WAITING_FOR_ALIGNMENT"
    assert s.broad_m15_activation is False


def test_78_6_plus_blocks_broad_m15_activation():
    e = FibonacciRetracementEngine()
    s = e.calculate(direction="BULLISH", origin=100, endpoint=120, current=104.28, aligned=True)
    assert s.retracement_pct >= 78.6
    assert s.state == "STRUCTURE_RISK"
    assert s.broad_m15_activation is False
    assert s.flag_early_access is False


def test_deep_but_sub_78_6_remains_broad_m15_eligible():
    e = FibonacciRetracementEngine()
    s = e.calculate(direction="BEARISH", origin=120, endpoint=100, current=115, aligned=True)
    assert 61.8 <= s.retracement_pct < 78.6
    assert s.state == "ACTIVE_DEEP_CORRECTION"
    assert s.broad_m15_activation is True


def test_qualified_h1_correction_latches_broad_m15_during_recovery_below_38_2():
    e = FibonacciRetracementEngine()
    s = e.calculate(
        direction="BULLISH", origin=100, endpoint=120, current=116,
        aligned=True, correction_qualified=True, max_correction_depth=0.50,
    )
    assert s.retracement_pct == 20.0
    assert s.state == "ACTIVE_LATCHED_RECOVERY"
    assert s.broad_m15_activation is True
    assert s.flag_early_access is False
    assert s.new_flag_discovery_allowed is False


def test_latched_h1_correction_resets_when_h1_starts_new_impulse():
    e = FibonacciRetracementEngine()
    s = e.calculate(
        direction="BULLISH", origin=112, endpoint=121, current=119.5,
        aligned=True, correction_qualified=False, max_correction_depth=0.0,
    )
    assert s.retracement_pct < 23.6
    assert s.broad_m15_activation is False
    assert s.flag_early_access is True
    assert s.new_flag_discovery_allowed is True


def test_h1_max_depth_latches_structure_risk_even_after_price_recovers():
    e = FibonacciRetracementEngine()
    s = e.calculate(
        direction="BEARISH", origin=120, endpoint=100, current=108,
        aligned=True, correction_qualified=True, max_correction_depth=0.80,
    )
    assert s.retracement_pct == 40.0
    assert s.state == "STRUCTURE_RISK"
    assert s.broad_m15_activation is False
    assert s.flag_early_access is False
