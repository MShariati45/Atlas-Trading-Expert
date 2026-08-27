# Atlas v0.24.23 - Broker Cost Evidence Gate

This checkpoint adds a deterministic, zero-AI, read-only audit between broker spread collection and any future DEMO_ONLY execution authorization.

Workflow after the market opens:
1. `run_official_four_currency_news_refresh.bat`
2. `run_mt5_broker_calibration.bat` (read-only; default 60 minutes)
3. `run_broker_calibration_audit.bat`
4. `run_mt5_demo_preflight.bat`

The audit requires sufficient positive spread samples, rejects stale tick evidence, compares observed P95 spread with the current approved paper policy, and **never changes thresholds automatically**. Slippage is intentionally still unvalidated because read-only observation cannot measure fill slippage. Execution remains locked.
