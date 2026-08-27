# Atlas v0.24.18 — Demo Execution Authorization

Built on v0.24.17. Adds a fail-closed, zero-API demo authorization gate while keeping MT5 mutations locked by default.

No demo enable file is included. Therefore downloading/running this package cannot enable order placement by itself.

Next Windows step: run `run_mt5_demo_preflight.bat` with MT5 open on the intended demo account and return `runtime/demo_preflight_report.json` for review before any demo execution switch is created.
