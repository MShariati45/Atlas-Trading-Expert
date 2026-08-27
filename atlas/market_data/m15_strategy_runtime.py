from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from atlas.core.state_store import NamespacedStateStore
from atlas.market_data.m15_live_runtime import M15LiveSnapshot, M15LiveSpecialistRuntime
from atlas.strategy.pattern_gate import PatternPolicyGate
from atlas.strategy.profile import (
    AtlasStrategyProfile,
    PATTERN_CHANNEL_BOUNDARY,
    PATTERN_CANDLESTICK_SR,
    PATTERN_FLAG,
    PATTERN_HS,
    PATTERN_IMPULSE,
    PATTERN_MULTIPLE,
    PATTERN_TRIANGLE,
    default_m15_first_profile,
)
from atlas.supervisor.runtime import SupervisorRuntime

_AGENT_TO_PATTERN = {
    "M15_IMPULSE_CORRECTION": PATTERN_IMPULSE,
    "M15_MULTIPLE_TOP_BOTTOM": PATTERN_MULTIPLE,
    "M15_FLAG_PENNANT": PATTERN_FLAG,
    "M15_TRIANGLE_WEDGE": PATTERN_TRIANGLE,
    "M15_HEAD_SHOULDERS": PATTERN_HS,
    "M15_CHANNEL": PATTERN_CHANNEL_BOUNDARY,
    "M15_CANDLESTICK_SR": PATTERN_CANDLESTICK_SR,
}


@dataclass(slots=True)
class DirectionalStrategyResult:
    direction: str
    snapshot: M15LiveSnapshot | None
    package: dict[str, Any] | None
    policy_allowed: bool
    policy_reason: str
    target_r: float | None


@dataclass(slots=True)
class M15FirstStrategySnapshot:
    symbol: str
    h4_trend: str
    h1_trend: str
    fibonacci_enabled: bool
    entry_search_allowed: bool
    reason_codes: list[str]
    long: DirectionalStrategyResult
    short: DirectionalStrategyResult


class M15FirstStrategyRuntime:
    """Dual-direction M15-first opportunity runtime.

    Both LONG and SHORT M15 specialists are allowed to discover structure. The
    symbol/pattern-specific H4/H1 research policy is applied *after* a mature M15
    trigger exists. This reverses the old hierarchy where H4/H1/Fibonacci could
    prevent the M15 layer from looking for opportunities at all.

    Fibonacci remains measurable upstream, but is disabled as a permission gate
    in the default v0.23 research profile.
    """

    def __init__(self, feed, store, *, profile: AtlasStrategyProfile | None = None, supervisor: SupervisorRuntime | None = None) -> None:
        self.profile = profile or default_m15_first_profile()
        self.supervisor = supervisor or SupervisorRuntime.from_strategy_profile(self.profile)
        self.gate = PatternPolicyGate(self.profile)
        self.long_runtime = M15LiveSpecialistRuntime(feed, NamespacedStateStore(store, "m15_long"), self.profile)
        self.short_runtime = M15LiveSpecialistRuntime(feed, NamespacedStateStore(store, "m15_short"), self.profile)

    @staticmethod
    def _pattern_from_package(pkg: dict[str, Any] | None) -> str | None:
        if not pkg:
            return None
        trigger = pkg.get("primary_trigger") or {}
        return _AGENT_TO_PATTERN.get(str(trigger.get("agent")))

    def _poll_direction(self, *, symbol: str, direction: str, h4_trend: str, h1_trend: str, fib_pct: float) -> DirectionalStrategyResult:
        runtime = self.long_runtime if direction == "LONG" else self.short_runtime
        snap = runtime.poll(
            symbol,
            direction,
            fib_pct,
            broad_m15_activation=True,
            new_flag_discovery_allowed=True,
            structure_risk=False,
        )
        pkg = snap.coordinator
        if pkg.get("coordination_state") != "READY_FOR_SUPERVISOR_REVIEW":
            return DirectionalStrategyResult(direction, snap, pkg, False, "NO_READY_M15_PACKAGE", None)
        pattern = self._pattern_from_package(pkg)
        if pattern is None:
            return DirectionalStrategyResult(direction, snap, pkg, False, "UNKNOWN_PRIMARY_PATTERN", None)
        decision = self.gate.evaluate(
            symbol=symbol,
            pattern=pattern,
            direction=direction,
            h4_trend=h4_trend,
            h1_trend=h1_trend,
        )
        pkg["strategy_pattern"] = pattern
        pkg["strategy_htf_gate"] = decision.reason_code
        pkg["target_r"] = decision.target_r
        pkg["fibonacci_permission_required"] = False
        return DirectionalStrategyResult(direction, snap, pkg, decision.allowed, decision.reason_code, decision.target_r)

    def poll(self, *, symbol: str, h4_trend: str, h1_trend: str, fib_pct: float = 0.0) -> M15FirstStrategySnapshot:
        """Poll both M15 directions. `h4_trend` is the H4 agent effective direction (formal trend unless an independently confirmed early trendline reversal is active)."""
        symbol = symbol.upper()
        if symbol not in self.profile.watchlist:
            blank = DirectionalStrategyResult("LONG", None, None, False, "SYMBOL_NOT_IN_WATCHLIST", None)
            blank2 = DirectionalStrategyResult("SHORT", None, None, False, "SYMBOL_NOT_IN_WATCHLIST", None)
            return M15FirstStrategySnapshot(symbol, h4_trend, h1_trend, self.profile.fibonacci_enabled, False, ["SYMBOL_NOT_IN_WATCHLIST"], blank, blank2)
        can_search, reasons = self.supervisor.entry_search_allowed(symbol)
        if not can_search:
            long = DirectionalStrategyResult("LONG", None, None, False, "ENTRY_SEARCH_LOCKED", None)
            short = DirectionalStrategyResult("SHORT", None, None, False, "ENTRY_SEARCH_LOCKED", None)
            return M15FirstStrategySnapshot(symbol, h4_trend, h1_trend, self.profile.fibonacci_enabled, False, reasons, long, short)
        long = self._poll_direction(symbol=symbol, direction="LONG", h4_trend=h4_trend, h1_trend=h1_trend, fib_pct=fib_pct)
        short = self._poll_direction(symbol=symbol, direction="SHORT", h4_trend=h4_trend, h1_trend=h1_trend, fib_pct=fib_pct)
        return M15FirstStrategySnapshot(symbol, h4_trend, h1_trend, self.profile.fibonacci_enabled, True, [], long, short)
