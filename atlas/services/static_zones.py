from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class ZoneState(str, Enum):
    ACTIVE = "ACTIVE"
    APPROACHING = "APPROACHING"
    TESTED = "TESTED"
    BROKEN = "BROKEN"
    INVALIDATED = "INVALIDATED"
    RETIRED = "RETIRED"

@dataclass(slots=True)
class StaticZone:
    timeframe: str
    low: float
    high: float
    strength: float = 0.5
    touch_count: int = 1
    state: ZoneState = ZoneState.ACTIVE
    label: str = ""

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

@dataclass(slots=True)
class ZoneAssessment:
    clear_for_target: bool
    blocking_zone: StaticZone | None = None
    nearest_support: StaticZone | None = None
    nearest_resistance: StaticZone | None = None
    reason_codes: list[str] = field(default_factory=list)

class StaticZoneService:
    """Caches D1/H4 zones and evaluates whether a target path is obstructed."""

    def __init__(self, zones: list[StaticZone] | None = None) -> None:
        self.zones = list(zones or [])

    def replace_zones(self, zones: list[StaticZone]) -> None:
        self.zones = list(zones)

    def active_zones(self) -> list[StaticZone]:
        return [z for z in self.zones if z.state in {ZoneState.ACTIVE, ZoneState.APPROACHING, ZoneState.TESTED}]

    def update_price(self, price: float, approach_fraction: float = 0.15) -> None:
        for z in self.active_zones():
            width = max(z.high - z.low, 1e-12)
            margin = max(width * approach_fraction, 1e-12)
            if z.contains(price):
                z.state = ZoneState.TESTED
            elif z.low - margin <= price <= z.high + margin:
                z.state = ZoneState.APPROACHING

    def mark_broken_if_closed_beyond(self, close: float, direction: str) -> None:
        for z in self.active_zones():
            if direction == "LONG" and close > z.high:
                z.state = ZoneState.BROKEN
            elif direction == "SHORT" and close < z.low:
                z.state = ZoneState.BROKEN

    def assess_target_path(self, current_price: float, target_price: float, direction: str) -> ZoneAssessment:
        active = self.active_zones()
        supports = [z for z in active if z.high < current_price]
        resistances = [z for z in active if z.low > current_price]
        nearest_support = max(supports, key=lambda z: z.high, default=None)
        nearest_resistance = min(resistances, key=lambda z: z.low, default=None)

        blocking = None
        if direction == "LONG":
            candidates = [z for z in active if current_price < z.low <= target_price]
            blocking = min(candidates, key=lambda z: z.low, default=None)
        elif direction == "SHORT":
            candidates = [z for z in active if target_price <= z.high < current_price]
            blocking = max(candidates, key=lambda z: z.high, default=None)

        if blocking:
            return ZoneAssessment(False, blocking, nearest_support, nearest_resistance, ["STATIC_ZONE_BLOCKED"])
        return ZoneAssessment(True, None, nearest_support, nearest_resistance, ["STATIC_ZONE_PATH_CLEAR"])
