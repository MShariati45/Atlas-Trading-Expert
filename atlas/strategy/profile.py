from __future__ import annotations

from dataclasses import dataclass, field

HTF_ANY = "ANY"
HTF_H4_ALIGNED_H1_ANY = "H4_ALIGNED_H1_ANY"
HTF_H4_ALIGNED_H1_OPPOSED = "H4_ALIGNED_H1_OPPOSED"
HTF_H4_H1_ALIGNED = "H4_H1_ALIGNED"
HTF_H4_H1_OPPOSED = "H4_H1_OPPOSED"

VALID_HTF_MODES = {
    HTF_ANY,
    HTF_H4_ALIGNED_H1_ANY,
    HTF_H4_ALIGNED_H1_OPPOSED,
    HTF_H4_H1_ALIGNED,
    HTF_H4_H1_OPPOSED,
}

PATTERN_IMPULSE = "IMPULSE_CORRECTION"
PATTERN_MULTIPLE = "MULTIPLE_TOP_BOTTOM"
PATTERN_FLAG = "FLAG_PENNANT"
PATTERN_TRIANGLE = "TRIANGLE_WEDGE"
PATTERN_HS = "HEAD_SHOULDERS"
PATTERN_CHANNEL_BOUNDARY = "CHANNEL_BOUNDARY_REJECTION"
PATTERN_CANDLESTICK_SR = "CANDLESTICK_SR_REVERSAL"

ALL_PATTERNS = {
    PATTERN_IMPULSE,
    PATTERN_MULTIPLE,
    PATTERN_FLAG,
    PATTERN_TRIANGLE,
    PATTERN_HS,
    PATTERN_CHANNEL_BOUNDARY,
    PATTERN_CANDLESTICK_SR,
}


@dataclass(frozen=True, slots=True)
class PatternRule:
    enabled: bool
    htf_mode: str = HTF_ANY
    target_r: float = 2.0
    note: str = ""

    def __post_init__(self) -> None:
        if self.htf_mode not in VALID_HTF_MODES:
            raise ValueError(f"unsupported HTF mode: {self.htf_mode}")
        if self.target_r <= 0:
            raise ValueError("target_r must be positive")


@dataclass(frozen=True, slots=True)
class SymbolStrategyProfile:
    symbol: str
    patterns: dict[str, PatternRule] = field(default_factory=dict)

    def rule(self, pattern: str) -> PatternRule:
        return self.patterns.get(pattern, PatternRule(False, note="PATTERN_NOT_CONFIGURED"))

    def enabled_patterns(self) -> set[str]:
        return {name for name, rule in self.patterns.items() if rule.enabled}


@dataclass(frozen=True, slots=True)
class AtlasStrategyProfile:
    name: str
    watchlist: tuple[str, ...]
    symbols: dict[str, SymbolStrategyProfile]
    fibonacci_enabled: bool = False
    fibonacci_visible: bool = False
    universal_h1_alignment_required: bool = False
    max_daily_risk_pct: float = 1.0
    risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 2
    max_trades_per_symbol_per_day: int = 1
    default_target_r: float = 2.0

    def __post_init__(self) -> None:
        missing = [s for s in self.watchlist if s not in self.symbols]
        if missing:
            raise ValueError(f"missing symbol profile(s): {missing}")
        if self.max_daily_risk_pct <= 0 or self.risk_per_trade_pct <= 0:
            raise ValueError("risk percentages must be positive")
        if self.max_trades_per_day < 1 or self.max_trades_per_symbol_per_day < 1:
            raise ValueError("trade limits must be positive")

    def symbol_profile(self, symbol: str) -> SymbolStrategyProfile | None:
        return self.symbols.get(symbol.upper())

    def pattern_rule(self, symbol: str, pattern: str) -> PatternRule:
        sp = self.symbol_profile(symbol)
        if sp is None:
            return PatternRule(False, note="SYMBOL_NOT_IN_WATCHLIST")
        return sp.rule(pattern)


# Research-to-runtime profile frozen from the audited 2025-08-19 -> 2026-08-19
# broker-native study. This is a candidate operating profile, not a claim of
# production readiness. Marginal/negative families are disabled per symbol.
def default_m15_first_profile() -> AtlasStrategyProfile:
    def r(enabled: bool, mode: str, target: float = 2.0, note: str = "") -> PatternRule:
        return PatternRule(enabled=enabled, htf_mode=mode, target_r=target, note=note)

    symbols = {
        "EURUSD": SymbolStrategyProfile("EURUSD", {
            PATTERN_CHANNEL_BOUNDARY: r(False, HTF_H4_ALIGNED_H1_OPPOSED, 2.0, "Disabled for demo profile by final pair-pattern selection"),
            PATTERN_HS: r(False, HTF_H4_ALIGNED_H1_OPPOSED, 2.0, "Disabled for demo profile by final pair-pattern selection"),
            PATTERN_IMPULSE: r(True, HTF_H4_ALIGNED_H1_OPPOSED, 2.0),
            PATTERN_TRIANGLE: r(True, HTF_H4_ALIGNED_H1_OPPOSED, 2.0),
            PATTERN_FLAG: r(False, HTF_H4_H1_ALIGNED, 2.0, "Positive but marginal in holdout"),
            PATTERN_MULTIPLE: r(False, HTF_H4_ALIGNED_H1_OPPOSED, 2.0, "Positive but below preferred quality threshold"),
            PATTERN_CANDLESTICK_SR: r(True, HTF_ANY, 2.0, "Selective live whitelist from v0.24.15 S/R-independent study"),
        }),
        "USDJPY": SymbolStrategyProfile("USDJPY", {
            PATTERN_CHANNEL_BOUNDARY: r(True, HTF_ANY, 2.0, "Primary USDJPY family; strong across HTF states"),
            PATTERN_FLAG: r(True, HTF_H4_H1_ALIGNED, 2.0, "Strong USDJPY continuation candidate"),
            PATTERN_HS: r(True, HTF_H4_H1_OPPOSED, 2.0, "Best reversal-context candidate"),
            PATTERN_TRIANGLE: r(True, HTF_H4_H1_ALIGNED, 2.0, "Positive aligned continuation candidate"),
            PATTERN_IMPULSE: r(False, HTF_H4_ALIGNED_H1_OPPOSED, 2.0, "Weak raw edge; disabled"),
            PATTERN_MULTIPLE: r(False, HTF_ANY, 2.0, "Negative raw edge; disabled"),
            PATTERN_CANDLESTICK_SR: r(True, HTF_ANY, 2.0, "Selective live whitelist from v0.24.15 S/R-independent study"),
        }),
        "USDCAD": SymbolStrategyProfile("USDCAD", {
            PATTERN_CHANNEL_BOUNDARY: r(True, HTF_H4_H1_OPPOSED, 3.0, "Strongest USDCAD channel candidate"),
            PATTERN_HS: r(False, HTF_H4_ALIGNED_H1_OPPOSED, 2.0, "Disabled for demo profile by final pair-pattern selection"),
            PATTERN_IMPULSE: r(False, HTF_H4_ALIGNED_H1_OPPOSED, 2.0, "Disabled for demo profile by final pair-pattern selection"),
            PATTERN_MULTIPLE: r(True, HTF_H4_ALIGNED_H1_OPPOSED, 2.0),
            PATTERN_TRIANGLE: r(True, HTF_H4_ALIGNED_H1_OPPOSED, 2.0),
            PATTERN_FLAG: r(False, HTF_H4_H1_OPPOSED, 2.0, "Too marginal"),
            PATTERN_CANDLESTICK_SR: r(True, HTF_ANY, 2.0, "Selective live whitelist from v0.24.15 S/R-independent study"),
        }),
        "XAUUSD": SymbolStrategyProfile("XAUUSD", {
            PATTERN_CHANNEL_BOUNDARY: r(True, HTF_H4_H1_OPPOSED, 3.0, "Best expectancy channel candidate"),
            PATTERN_FLAG: r(True, HTF_H4_ALIGNED_H1_ANY, 2.0),
            PATTERN_HS: r(True, HTF_H4_ALIGNED_H1_ANY, 2.0),
            PATTERN_IMPULSE: r(True, HTF_H4_ALIGNED_H1_ANY, 2.0),
            PATTERN_MULTIPLE: r(True, HTF_H4_ALIGNED_H1_ANY, 2.0),
            PATTERN_TRIANGLE: r(True, HTF_H4_ALIGNED_H1_ANY, 2.0),
            PATTERN_CANDLESTICK_SR: r(True, HTF_ANY, 2.0, "Selective live whitelist from v0.24.15 S/R-independent study"),
        }),
    }
    return AtlasStrategyProfile(
        name="ATLAS_M15_FIRST_DEMO_CANDIDATE_V0_24_17",
        watchlist=("EURUSD", "USDJPY", "USDCAD", "XAUUSD"),
        symbols=symbols,
        fibonacci_enabled=False,
        fibonacci_visible=False,
        universal_h1_alignment_required=False,
        max_daily_risk_pct=1.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=2,
        max_trades_per_symbol_per_day=1,
        default_target_r=2.0,
    )


def legacy_compat_profile() -> AtlasStrategyProfile:
    """Compatibility profile preserving the v0.22.7 caller contract."""
    all_on = {
        PATTERN_IMPULSE: PatternRule(True),
        PATTERN_MULTIPLE: PatternRule(True),
        PATTERN_FLAG: PatternRule(True),
        PATTERN_TRIANGLE: PatternRule(True),
        PATTERN_HS: PatternRule(True),
        PATTERN_CHANNEL_BOUNDARY: PatternRule(True),
        PATTERN_CANDLESTICK_SR: PatternRule(False, note="Disabled in legacy compatibility profile"),
    }
    symbols = {s: SymbolStrategyProfile(s, dict(all_on)) for s in ("EURUSD", "USDCAD", "XAUUSD", "USDJPY", "AUDUSD", "USDCHF", "GBPJPY")}
    return AtlasStrategyProfile(
        name="V0_22_7_COMPAT",
        watchlist=tuple(symbols),
        symbols=symbols,
        fibonacci_enabled=True,
        fibonacci_visible=True,
        universal_h1_alignment_required=True,
    )
