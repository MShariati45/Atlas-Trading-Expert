from __future__ import annotations

from atlas.execution.controlled_demo_gate import BrokerContract
from atlas.execution.models import AccountConfig


class MT5BrokerContractService:
    """Build BrokerContract using MT5 account-currency P/L calculation when available."""
    def __init__(self, bridge) -> None:
        self.bridge = bridge

    def build(self, account: AccountConfig, symbol: str, direction: str, entry: float, stop: float) -> BrokerContract:
        self.bridge.connect(account)
        mt5 = self.bridge._module()
        broker_symbol = self.bridge.broker_symbol(account, symbol)
        if not mt5.symbol_select(broker_symbol, True):
            raise RuntimeError("BROKER_SYMBOL_SELECT_FAILED")
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            raise RuntimeError("BROKER_SYMBOL_INFO_UNAVAILABLE")
        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "LONG" else mt5.ORDER_TYPE_SELL
        loss_per_lot = None
        if hasattr(mt5, "order_calc_profit"):
            value = mt5.order_calc_profit(order_type, broker_symbol, 1.0, float(entry), float(stop))
            if value is not None:
                loss_per_lot = abs(float(value))
        return BrokerContract(
            point=float(getattr(info, "point", 0.0) or 0.0),
            tick_size=float(getattr(info, "trade_tick_size", 0.0) or getattr(info, "point", 0.0) or 0.0),
            tick_value=float(getattr(info, "trade_tick_value_loss", 0.0) or getattr(info, "trade_tick_value", 0.0) or 0.0),
            volume_min=float(getattr(info, "volume_min", 0.0) or 0.0),
            volume_max=float(getattr(info, "volume_max", 0.0) or 0.0),
            volume_step=float(getattr(info, "volume_step", 0.0) or 0.0),
            stops_level_points=int(getattr(info, "trade_stops_level", 0) or 0),
            loss_per_lot_at_stop=loss_per_lot,
        )
