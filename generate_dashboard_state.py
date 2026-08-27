import json
from pathlib import Path

from atlas.agents.h1_structure import H1StructureAgent
from atlas.agents.h4_structure import H4StructureAgent, PricePoint
from atlas.agents.fibonacci import FibonacciRetracementEngine
from atlas.agents.m15_impulse_correction import M15ImpulseCorrectionAgent
from atlas.core.events import Event


def main() -> None:
    symbol = "EURUSD"
    h4 = H4StructureAgent()
    h4.seed(symbol, trend="BULLISH", origin=PricePoint(1.1500, "H4-A"), endpoint=PricePoint(1.1700, "H4-B"), control_pivot=PricePoint(1.1500, "H4-A"))
    h4_report = h4.handle(Event(type="H4_BAR_CLOSED", symbol=symbol, payload={"time":"H4-C","high":1.1692,"low":1.1645,"close":1.1660}))

    h1 = H1StructureAgent()
    h1.seed(symbol, trend="BULLISH", origin=PricePoint(1.1550, "H1-A"), endpoint=PricePoint(1.1700, "H1-B"), control_pivot=PricePoint(1.1550, "H1-A"), h4_trend="BULLISH")
    h1_report = h1.handle(Event(type="H1_BAR_CLOSED", symbol=symbol, payload={"time":"H1-C","high":1.1688,"low":1.1628,"close":1.1635,"h4_trend":"BULLISH"}))

    fib = FibonacciRetracementEngine().calculate(
        direction=h1_report.data["trend"],
        origin=h1_report.data["strategic_origin"]["price"],
        endpoint=h1_report.data["strategic_endpoint"]["price"],
        current=1.1635,
        aligned=h1_report.data["h4_relationship"] == "ALIGNED",
    )

    m15 = M15ImpulseCorrectionAgent()
    m15.seed(
        symbol,
        trend="BEARISH",
        control_pivot=PricePoint(1.1640, "M15-LH"),
        endpoint=PricePoint(1.1600, "M15-LL"),
        permitted_direction="LONG",
    )
    m15_report = m15.handle(Event(type="M15_BAR_CLOSED", symbol=symbol, payload={
        "time":"M15-CHOCH","high":1.1650,"low":1.1615,"close":1.1644,
        "spread":0.00008,"atr":0.0009,"wick_stat":0.00024,"tick_size":0.00001,
    }))

    state = {
        "symbol": symbol,
        "h4": {"trend": h4_report.data["trend"], "phase": h4_report.data["phase"], "state_version": h4_report.state_version},
        "h1": {"trend": h1_report.data["trend"], "phase": h1_report.data["phase"], "relationship": h1_report.data["h4_relationship"], "state_version": h1_report.state_version},
        "fib": {"retracement_pct": fib.retracement_pct, "zone": fib.zone, "broad_m15_activation": fib.broad_m15_activation, "flag_early_access": fib.flag_early_access},
        "m15": {
            "phase": m15_report.data["phase"],
            "reason": m15_report.data["last_reason_code"],
            "entry": m15_report.data["trigger_entry_reference"],
            "stop": m15_report.data["final_stop"],
            "state_version": m15_report.state_version,
        },
        "supervisor": {"decision":"WAIT", "reason":"M15 bullish CHoCH is detected, but Atlas correctly waits for a new higher high, meaningful higher low, and BOS before an entry candidate can reach the Supervisor."},
        "runtime": {"risk_available_pct":1.0, "trades_today":0, "max_trades":2, "symbol_lock":"AVAILABLE"}
    }
    out = Path(__file__).parent / "dashboard" / "state.json"
    out.write_text(json.dumps(state, indent=2))
    print(out)

if __name__ == "__main__":
    main()
