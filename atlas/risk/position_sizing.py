def risk_amount(equity: float, risk_pct: float) -> float:
    return equity * (risk_pct / 100.0)

def units_from_stop(risk_cash: float, cash_loss_per_unit_at_stop: float) -> float:
    if cash_loss_per_unit_at_stop <= 0:
        raise ValueError("cash_loss_per_unit_at_stop must be positive")
    return risk_cash / cash_loss_per_unit_at_stop
