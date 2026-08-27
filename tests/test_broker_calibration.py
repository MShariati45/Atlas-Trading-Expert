from atlas.services.broker_calibration import summarize_spreads


def test_spread_summary_is_observation_only_and_percentiles_are_ordered():
    r=summarize_spreads([0,1,1,2,3,5,10])
    d=r.to_dict()
    assert d['samples']==7
    assert d['zero_spread_samples']==1
    assert d['p50_spread_points'] <= d['p90_spread_points'] <= d['p95_spread_points'] <= d['p99_spread_points'] <= d['max_spread_points']
    assert d['slippage_status']=='NOT_MEASURABLE_READ_ONLY'
    assert d['calibration_status']=='OBSERVATION_ONLY_NOT_ACTIVE_LIMITS'
