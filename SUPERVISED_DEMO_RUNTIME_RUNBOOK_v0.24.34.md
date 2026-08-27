# Atlas v0.24.34 - Supervised DEMO Runtime Activation

## Purpose
v0.24.34 activates one persistent, fail-closed runtime that combines the live Owner dashboard, H4/H1 structure observation, M15 specialist/coordinator discovery, static-zone and live-news Supervisor review, adaptive spread checks, account risk state, the existing controlled DEMO new-order gate, and the existing supervised DEMO trade-management boundary.

## Safety invariants
- REAL/LIVE accounts remain forbidden. MT5 `trade_mode` is authoritative.
- Default startup is observation-only. `start_supervised_demo_runtime.bat` cannot transmit orders.
- A candidate cannot execute merely because the dashboard says DEMO VERIFIED.
- Broker-cost policy must be explicitly approved **and execution/slippage validated**. `PAPER_ONLY` is never executable.
- Live news must be available/fresh; stale/unavailable news fails closed.
- H4 human approval remains mandatory for the existing controlled DEMO authorization path.
- Risk remains 0.5% per trade, max 1.0% daily, max two trades/day, max one trade/symbol/day.
- New positions have one legal mutation path: `ControlledDemoExecutionGate -> DemoOnlyMT5Transport`.
- Existing positions have one legal mutation path: `SupervisedDemoManagementGate -> DemoOnlyTradeManagementTransport`.
- Legacy direct MT5 mutation methods remain disabled.

## VPS activation now (observation-only)
1. Stop the old `start_dashboard_activation.bat` window with Ctrl+C.
2. Run `run_supervised_demo_preflight.bat` and keep the report.
3. Run `start_supervised_demo_runtime.bat`.
4. Restart the `Atlas Web` scheduled task so the updated UI/read model is loaded.
5. Refresh `https://app.atlastradingexpert.com` with Ctrl+F5.

The dashboard will show supervised runtime readiness and blockers. In the current checkpoint, execution should remain LOCKED until broker slippage/execution-cost validation, live-news readiness, demo preflight, H4 approval, and explicit Owner arming are all satisfied.

## Explicit DEMO arming (not performed by this package)
This package intentionally does not ship an enabled `runtime/DEMO_EXECUTION_ENABLE.json` and does not set `ATLAS_DEMO_EXECUTION=YES`.
When all preflight blockers are cleared, Owner authorization must deliberately create the enable file, set the environment acknowledgement, and launch `run_supervised_demo_runtime.py --allow-execution`. Even then, each signal still passes every controlled gate immediately before broker transmission.

## Credentials
Do not store MT5 passwords in source files or browser-visible JSON. Use the existing environment-referenced password mechanism.
