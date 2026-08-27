from atlas.services.static_zones import StaticZone, StaticZoneService, ZoneState

def test_long_target_blocked_by_resistance():
    svc = StaticZoneService([StaticZone("H4", 1.1050, 1.1060)])
    a = svc.assess_target_path(1.1000, 1.1100, "LONG")
    assert not a.clear_for_target
    assert a.blocking_zone is not None

def test_short_target_clear_when_no_support_in_path():
    svc = StaticZoneService([StaticZone("H4", 1.1050, 1.1060)])
    a = svc.assess_target_path(1.1000, 1.0950, "SHORT")
    assert a.clear_for_target

def test_zone_state_updates_on_approach_and_break():
    z = StaticZone("D1", 100, 102)
    svc = StaticZoneService([z])
    svc.update_price(101)
    assert z.state is ZoneState.TESTED
    svc.mark_broken_if_closed_beyond(103, "LONG")
    assert z.state is ZoneState.BROKEN
