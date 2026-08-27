# MT5 Demo Integration Status - v0.12

## Implemented
- Read-only MT5 market-data feed with lazy MetaTrader5 import.
- Account snapshot: balance, equity, margin, leverage and trade permission.
- Symbol metadata: digits, point, tick size/value, volume constraints, stop/freeze levels.
- Live tick / bid / ask / spread reads.
- Completed H4, H1 and M15 candle ingestion. Position 0 (forming candle) is deliberately excluded.
- Open-position read surface.
- Read-only demo readiness validator.
- Safe command-line demo connectivity probe. It never sends a market order.

## Deliberately disabled
- Automated order submission from the demo probe.
- Live execution remains opt-in and should only be enabled after broker-specific fill, stop-distance, symbol naming and order-check validation.

## Required on the user's Windows MT5 machine
1. MetaTrader 5 desktop terminal installed and logged into the intended demo account.
2. Python installed.
3. MetaTrader5 Python package installed.
4. Atlas package extracted locally.
5. Run the read-only probe first and confirm every required symbol/timeframe is readable.

## Next milestone
Connect incoming closed-bar events to the Atlas Event Orchestrator and persisted H4/H1/Fibonacci/M15 state, then expose the resulting live observation state in the dashboard before enabling demo order sends.
