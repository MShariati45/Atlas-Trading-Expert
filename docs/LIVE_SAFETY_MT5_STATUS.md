# Atlas v0.11 - Live Safety / MetaTrader Boundary

Implemented:
- Cached D1/H4 static-zone service with target-path blocking.
- High-impact News Guard contract with entry blackout and open-trade review windows.
- Spread/slippage service and net executable R:R calculation.
- Vancouver trading-week governance: Sunday market-open through Thursday entries; Friday new entries blocked; configurable Friday force-flat window.
- LiveSafetyService that converts these independent services into Supervisor hard gates.
- Optional MetaTrader5 Python bridge with lazy import. It is safe to package/test without MT5 installed.

Execution remains disabled by default. Broker-specific fill policy, symbol metadata, live news feed adapter, static-zone detection/calibration, and demo-account validation are still required before live trading.
