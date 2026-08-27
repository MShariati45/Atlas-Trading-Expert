# Atlas v0.23.8 — MT5 Demo Preflight

## Purpose
This checkpoint prepares Atlas for a real Windows MetaTrader 5 demo terminal while keeping order transmission hard locked.

## Readiness levels
1. **Read-only observation** requires a connected MT5 terminal, valid account identity, all four canonical Atlas symbols mapped to usable broker symbols, valid contract metadata, fresh ticks, and sufficient/fresh completed D1/H4/H1/M15 history.
2. **Paper Supervisor readiness** additionally requires a working live scheduled-news provider. Broker spread/slippage limits must be calibrated/configured before the market-cost gate may approve a candidate.
3. **Execution** remains disabled. No preflight or observer script enables it.

## Required history
- D1: 500 completed bars (Static Zone service)
- H4: 900 completed bars (Static Zone service; exceeds H4 structure bootstrap minimum)
- H1: 600 completed bars (structure bootstrap)
- M15: 240 completed bars (specialist runtime)

## Broker symbol mapping
Atlas retains canonical symbols `EURUSD`, `USDJPY`, `USDCAD`, and `XAUUSD`. If the broker adds a suffix or prefix, pass mappings to the preflight/observer rather than editing strategy symbols. Example: `--symbol-map XAUUSD=XAUUSD.a`.

## Critical fixes made in v0.23.8
- Corrected positional construction of MT5 connection settings in `run_m15_first_observer.py` and `run_collect_mt5_history.py`; terminal path/login/password/server are now assigned by keyword.
- Added canonical-to-broker symbol translation to the read-only MT5 feed.
- Expanded the demo probe from a shallow connectivity check to terminal/account/symbol/contract/tick/history/freshness validation.
- Removed the unsafe paper-mode shortcut that set `max_spread_points` to twice the current spread. If calibrated broker market-cost limits are absent, Supervisor receives UNKNOWN and must WAIT.
- Live news is explicitly required for paper-Supervisor readiness.

## Windows command
Run `run_mt5_demo_preflight.bat` from the Atlas folder while the intended MT5 demo terminal is open and logged in.

Optional exact account verification:
`run_mt5_demo_preflight.bat --login 123456 --server "Broker-Demo"`

Optional symbol aliases:
`run_mt5_demo_preflight.bat --symbol-map EURUSD=EURUSD.a --symbol-map USDJPY=USDJPY.a --symbol-map USDCAD=USDCAD.a --symbol-map XAUUSD=XAUUSD.a`

The machine-readable result is written to `runtime/demo_preflight_report.json`.
