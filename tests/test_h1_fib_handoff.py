import csv
from pathlib import Path

from atlas.agents.fibonacci import FibonacciRetracementEngine
from atlas.agents.h1_structure import H1StructureEngine
from atlas.core.structure_types import PricePoint


def test_real_eurusd_replay_handoff_uses_latest_h1_impulse_not_historical_seed():
    engine = H1StructureEngine()
    state = engine.seed(
        trend="BULLISH",
        origin=PricePoint(117041.0, "2021-03-31 07:00:00"),
        endpoint=PricePoint(122664.0, "2021-05-25 15:00:00"),
        control_pivot=PricePoint(117041.0, "2021-03-31 07:00:00"),
    )
    dataset = Path(__file__).parents[1] / "EURUSDh1.csv"
    last_close = None
    with dataset.open(newline="") as fh:
        rows = csv.reader(fh)
        next(rows, None)
        for row in rows:
            timestamp = row[0]
            if timestamp <= "2021-05-25 15:00:00":
                continue
            last_close = float(row[4])
            state = engine.update(
                state,
                {"time": timestamp, "high": float(row[2]), "low": float(row[3]), "close": last_close},
            )

    assert state.trend == "BEARISH"
    assert state.strategic_origin.time == "2022-03-02 18:00:00"
    assert state.strategic_endpoint.time == "2022-03-04 15:00:00"
    assert state.strategic_origin.time != "2021-03-31 07:00:00"
    assert state.correction_qualified is False

    fib = FibonacciRetracementEngine().calculate(
        direction=state.trend,
        origin=state.strategic_origin.price,
        endpoint=state.strategic_endpoint.price,
        current=last_close,
        aligned=True,
        correction_qualified=state.correction_qualified,
        max_correction_depth=state.correction_depth,
    )
    assert fib.origin_price == state.strategic_origin.price
    assert fib.endpoint_price == state.strategic_endpoint.price
    assert fib.state == "ACTIVE_SHALLOW"
    assert fib.broad_m15_activation is False
