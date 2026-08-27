from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from atlas.core.enums import Decision, SupervisorMode
from atlas.risk.policy import RiskPolicy
from .decision_engine import SupervisorDecisionEngine, DecisionResult

@dataclass(slots=True)
class DailyRiskLedger:
    trading_date: str
    trades_opened: int = 0
    risk_committed_pct: float = 0.0
    traded_symbols: set[str] = field(default_factory=set)

    def can_trade_symbol(self, symbol: str, policy: RiskPolicy, proposed_risk_pct: float) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if self.trades_opened >= policy.max_trades_per_day:
            reasons.append('MAX_DAILY_TRADES_REACHED')
        if symbol in self.traded_symbols:
            reasons.append('SYMBOL_ALREADY_TRADED_TODAY')
        if self.risk_committed_pct + proposed_risk_pct > policy.max_daily_risk_pct + 1e-9:
            reasons.append('MAX_DAILY_RISK_EXCEEDED')
        return (not reasons, reasons)

    def commit(self, symbol: str, risk_pct: float) -> None:
        self.trades_opened += 1
        self.risk_committed_pct += float(risk_pct)
        self.traded_symbols.add(symbol)

@dataclass(slots=True)
class SupervisorContext:
    symbol: str
    proposed_risk_pct: float
    day_ok: bool | None
    session_ok: bool | None
    alignment_ok: bool | None
    fib_ok: bool | None
    m15_ok: bool | None
    freshness_ok: bool | None
    static_zone_ok: bool | None
    spread_ok: bool | None
    news_ok: bool | None
    structural_stop_ok: bool | None
    net_rr_ok: bool | None
    # Optional directional context. When supplied, Atlas derives alignment from
    # H4 effective direction (early confirmed trendline reversal may override
    # search direction without rewriting the formal strategic trend).
    h4_strategic_trend: str | None = None
    h4_early_direction: str | None = None
    h1_trend: str | None = None
    requested_direction: str | None = None  # LONG / SHORT
    pattern_policy_resolved: bool = False  # True only after PatternPolicyGate has approved this candidate

@dataclass(slots=True)
class SupervisorRuntimeResult:
    result: DecisionResult
    mode: SupervisorMode
    gates: dict[str, bool | None]
    reason_codes: list[str]

class SupervisorRuntime:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()
        self.engine = SupervisorDecisionEngine()
        self.mode = SupervisorMode.STRUCTURE_MONITORING
        self.ledger = DailyRiskLedger(trading_date=date.today().isoformat())
        self.open_positions = 0

    @classmethod
    def from_strategy_profile(cls, profile) -> "SupervisorRuntime":
        return cls(RiskPolicy.from_strategy_profile(profile))

    def entry_search_allowed(self, symbol: str | None = None) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if self.ledger.trades_opened >= self.policy.max_trades_per_day:
            reasons.append("MAX_DAILY_TRADES_REACHED_SEARCH_DISABLED")
        if self.ledger.risk_committed_pct >= self.policy.max_daily_risk_pct - 1e-9:
            reasons.append("MAX_DAILY_RISK_REACHED_SEARCH_DISABLED")
        if symbol is not None and symbol in self.ledger.traded_symbols:
            reasons.append("SYMBOL_ALREADY_TRADED_TODAY_SEARCH_DISABLED")
        return (not reasons, reasons)

    def reset_day(self, trading_date: str) -> None:
        self.ledger = DailyRiskLedger(trading_date=trading_date)
        if self.open_positions == 0:
            self.mode = SupervisorMode.STRUCTURE_MONITORING

    @staticmethod
    def _directional_alignment(ctx: SupervisorContext) -> tuple[bool | None, list[str]]:
        # v0.23.6: pattern-specific HTF policy is resolved upstream by
        # PatternPolicyGate. If that decision is explicitly supplied, the
        # Supervisor must not replace it with a universal H4/H1-alignment rule.
        if ctx.pattern_policy_resolved:
            return ctx.alignment_ok, ["PATTERN_SPECIFIC_HTF_POLICY_ACCEPTED"]
        provided = any(x is not None for x in (
            ctx.h4_strategic_trend, ctx.h4_early_direction, ctx.h1_trend, ctx.requested_direction
        ))
        if not provided:
            return ctx.alignment_ok, []
        if not all(x is not None for x in (ctx.h4_strategic_trend, ctx.h1_trend, ctx.requested_direction)):
            return None, ["DIRECTIONAL_CONTEXT_INCOMPLETE"]
        requested = {"LONG": "BULLISH", "SHORT": "BEARISH"}.get(str(ctx.requested_direction).upper())
        if requested is None:
            return False, ["INVALID_REQUESTED_DIRECTION"]
        strategic = str(ctx.h4_strategic_trend).upper()
        early = str(ctx.h4_early_direction or "NONE").upper()
        h1 = str(ctx.h1_trend).upper()
        effective = early if early in {"BULLISH", "BEARISH"} else strategic
        ok = effective == requested and h1 == requested
        reasons = []
        if ok and early in {"BULLISH", "BEARISH"} and early != strategic:
            reasons.append("EARLY_H4_REVERSAL_PATH_VALID")
        elif ok:
            reasons.append("STANDARD_H4_H1_ALIGNMENT_VALID")
        else:
            reasons.append("H4_H1_EFFECTIVE_DIRECTION_MISMATCH")
        return ok, reasons

    def review(self, ctx: SupervisorContext) -> SupervisorRuntimeResult:
        symbol_ok, risk_reasons = self.ledger.can_trade_symbol(ctx.symbol, self.policy, ctx.proposed_risk_pct)
        alignment_gate, direction_reasons = self._directional_alignment(ctx)
        gates = {
            'day_ok': ctx.day_ok,
            'session_ok': ctx.session_ok,
            'alignment_ok': alignment_gate,
            'fib_ok': ctx.fib_ok,
            'm15_ok': ctx.m15_ok,
            'freshness_ok': ctx.freshness_ok,
            'static_zone_ok': ctx.static_zone_ok,
            'spread_ok': ctx.spread_ok,
            'news_ok': ctx.news_ok,
            'symbol_lock_ok': ctx.symbol not in self.ledger.traded_symbols,
            'daily_trade_limit_ok': self.ledger.trades_opened < self.policy.max_trades_per_day,
            'daily_risk_ok': self.ledger.risk_committed_pct + ctx.proposed_risk_pct <= self.policy.max_daily_risk_pct + 1e-9,
            'structural_stop_ok': ctx.structural_stop_ok,
            'net_rr_ok': ctx.net_rr_ok,
        }
        result = self.engine.decide(gates)
        reasons = list(result.reason_codes) + direction_reasons + risk_reasons
        self.mode = SupervisorMode.CANDIDATE_REVIEW if result.decision is not Decision.APPROVE else SupervisorMode.EXECUTION_PENDING
        return SupervisorRuntimeResult(result, self.mode, gates, reasons)

    def mark_trade_opened(self, symbol: str, risk_pct: float) -> None:
        self.ledger.commit(symbol, risk_pct)
        self.open_positions += 1
        self.mode = SupervisorMode.TRADE_FOCUS

    def mark_trade_closed(self) -> None:
        self.open_positions = max(0, self.open_positions - 1)
        if self.open_positions:
            self.mode = SupervisorMode.TRADE_FOCUS
        elif self.ledger.trades_opened >= self.policy.max_trades_per_day or self.ledger.risk_committed_pct >= self.policy.max_daily_risk_pct - 1e-9:
            self.mode = SupervisorMode.DAILY_LOCKED
        else:
            self.mode = SupervisorMode.POST_TRADE_UPDATE
