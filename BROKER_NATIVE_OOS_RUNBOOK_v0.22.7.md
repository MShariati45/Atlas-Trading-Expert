# Atlas v0.22.7 - Broker-native OOS runbook

This checkpoint does not change Atlas strategy rules. It turns the v0.22.6 broker-native validation boundary into a reproducible Windows/MT5 handoff workflow.

## Safety boundary

All collection, audit, and replay commands in this runbook are read-only. The collector uses the read-only MT5 market-data adapter. It does not send, modify, or close orders.

## Prerequisites on the Windows MT5 machine/VPS

1. MetaTrader 5 desktop is installed and logged into the intended demo/broker account.
2. Python 3.11+ is installed.
3. Install the optional Windows dependencies:

   `python -m pip install -r requirements-mt5-windows.txt`

4. Confirm the symbols in `config/demo_watchlist.json` match the broker's symbol names. If the broker uses suffixes such as `EURUSD.a`, edit the watchlist before collection rather than renaming CSV files afterward.

## Step 1 - Collect native history

Run:

`run_mt5_oos_collection.bat`

Optional custom dataset path:

`run_mt5_oos_collection.bat historical_data\my_broker_oos`

The helper first runs a read-only EURUSD/GBPUSD connectivity probe, then collects approximately one year of completed D1/H4/H1/M15 bars for the configured watchlist. The output includes `manifest.json`, broker/account metadata, per-file SHA-256 hashes, spread observations, and the bar CSVs.

## Step 2 - Historical high-impact news

Create `historical_news.csv` using `examples/historical_news_template.csv` as the schema:

`event_time_utc,currency,impact,title,event_id`

Use UTC, one event per row. For Atlas to label the replay fully gated, the file must contain the relevant historical high-impact events for the replay period. Missing news is intentionally fail-closed as `NEWS_DATA_UNAVAILABLE`.

## Step 3 - Audit the collected dataset

Run:

`run_mt5_oos_audit.bat historical_data\broker_native_oos historical_news.csv`

The audit verifies manifest completeness, D1/H4/H1/M15 presence, hashes, row counts, monotonic timestamps, duplicates, malformed rows, spread observations, and news-file readability. `replay_permission` must be `true` before a study is described as fully gated.

## Step 4 - Run a broker-native replay

Choose an interval that leaves enough earlier H4/H1 bars for bootstrap. Example:

`run_mt5_oos_replay.bat historical_data\broker_native_oos historical_news.csv 2025-08-01T00:00:00+00:00 2026-08-01T00:00:00+00:00`

The helper runs EURUSD and GBPUSD through native H4/H1 structure, downstream alignment, H1 Fibonacci gating, live M15 specialists, causal D1/H4 static zones, and historical news gating. It does not place trades.

## Step 5 - Package the handoff

Run:

`package_mt5_oos_results.bat`

This creates `Atlas_MT5_OOS_Data.zip` from the available dataset, news, audit, and replay outputs. Upload that ZIP back into the Atlas conversation so the fixed-2R control and the predeclared research challengers can be scored on truly unseen broker-native data.

## Frozen research comparison

Do not tune after viewing the new data. The control remains fixed 2R. The predeclared Flag/Pennant management research matrix is: fixed 2R control; breakeven at +1R; 1R trail activated at +2R with the 2R TP removed; and 1R trail activated at +2.5R with the 2R TP removed. These are research challengers only and are not live Atlas rules.
