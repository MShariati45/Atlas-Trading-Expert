from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_daily_risk_pct: float = 1.0
    default_risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 2
    max_trades_per_symbol_per_day: int = 1
    default_target_r: float = 2.0
    # Optional extra post-cost R:R floor. Atlas already hard-gates spread and
    # slippage separately; leaving this unset preserves the fixed gross-2R
    # strategy without accidentally requiring net R:R to remain exactly 2.0.
    min_net_rr_after_costs: float | None = None
    breakeven_trigger_r: float = 1.4
    allow_new_trades_friday: bool = False
    @classmethod
    def from_strategy_profile(cls, profile) -> "RiskPolicy":
        return cls(
            max_daily_risk_pct=float(profile.max_daily_risk_pct),
            default_risk_per_trade_pct=float(profile.risk_per_trade_pct),
            max_trades_per_day=int(profile.max_trades_per_day),
            max_trades_per_symbol_per_day=int(profile.max_trades_per_symbol_per_day),
            default_target_r=float(profile.default_target_r),
            min_net_rr_after_costs=None,
            breakeven_trigger_r=1.4,
            allow_new_trades_friday=False,
        )

