from datetime import datetime
from zoneinfo import ZoneInfo
from atlas.services.safety import LiveSafetyService, SafetyInputs
from atlas.services.static_zones import StaticZone, StaticZoneService
from atlas.supervisor.runtime import SupervisorRuntime
from atlas.core.enums import Decision

def base_input():
    return SafetyInputs(
        symbol="EURUSD", direction="LONG", entry=1.1000, stop=1.0990, target=1.1030,
        point_size=0.0001, spread_points=1, expected_slippage_points=0,
        max_spread_points=3, max_slippage_points=2, proposed_risk_pct=0.5,
        alignment_ok=True, fib_ok=True, m15_ok=True, freshness_ok=True,
        structural_stop_ok=True,
        now=datetime(2026, 8, 20, 10, tzinfo=ZoneInfo("America/Vancouver")),
    )

def test_safety_context_can_approve_clean_setup():
    ctx, _ = LiveSafetyService().build_context(base_input())
    result = SupervisorRuntime().review(ctx)
    assert result.result.decision is Decision.APPROVE

def test_static_zone_flows_into_supervisor_rejection():
    zones = StaticZoneService([StaticZone("H4", 1.1010, 1.1020)])
    ctx, _ = LiveSafetyService(zones=zones).build_context(base_input())
    result = SupervisorRuntime().review(ctx)
    assert result.result.decision is Decision.REJECT
    assert "GATE_FAILED:static_zone_ok" in result.result.reason_codes
