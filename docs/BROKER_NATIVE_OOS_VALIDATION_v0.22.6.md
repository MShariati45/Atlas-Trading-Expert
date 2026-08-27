# Atlas v0.22.6 - Broker-native out-of-sample validation harness

## Purpose
Preserve v0.22.5 strategy behavior while moving validation onto unseen broker-native MT5 D1/H4/H1/M15 history.

## Safety / anti-overfit rules
- No pattern, threshold, stop, target, or trade-management changes in this checkpoint.
- Native H1/H4 must be used; do not synthesize them from M15 for the broker-native study.
- Every collected CSV is verified against the collector manifest SHA-256 and row count before replay.
- Historical-news data is mandatory for a fully gated result. If it is unavailable, Atlas must label the replay incomplete / news-unvalidated rather than assuming `news_ok=True`.
- D1/H4 static zones must be derived from completed bars available at each historical timestamp; no future-zone leakage.
- Monday-Thursday, daily limits, structural-stop, spread/slippage and fixed gross 2R remain frozen control behavior.
- Runner/trailing ideas remain research-only and are not part of the control.

## Workflow on Windows/VPS with MT5
1. `python run_collect_mt5_history.py --watchlist config/demo_watchlist.json --out historical_data/oos_2025_2026`
2. Supply historical high-impact calendar data using `examples/historical_news_template.csv` shape.
3. `python run_audit_mt5_oos_dataset.py --dataset historical_data/oos_2025_2026 --historical-news historical_news.csv --out historical_data/oos_2025_2026/audit.json`
4. Only if the audit passes, run the chronological Atlas replay/paper Supervisor report.

## Required report outputs
Per symbol and aggregate: eligible bars, H4/H1 alignment state, Fibonacci state, specialist events, Coordinator state, Supervisor gate decisions/reasons, stop distance, spread/slippage, static-zone block, news block, fixed-2R outcome, MFE/MAE, and daily risk/trade-limit effects.

## Interpretation
This checkpoint creates the validation boundary. It does not claim profitability or production readiness until unseen broker-native data has been collected and replayed.
