# Atlas v0.18 - Historical Data Collection

## Purpose
Collect a broker-specific, read-only one-year D1/H4/H1/M15 dataset directly from the connected MetaTrader 5 demo terminal for every configured watchlist symbol.

## Safety
- Read-only market/account queries only.
- No order sending.
- Current/incomplete bars are excluded by using an end time safely behind the active M15 bar.
- A SHA-256 hash and row count are recorded for every CSV in `manifest.json`.

## Dataset
Each symbol receives D1, H4, H1 and M15 CSV files with UTC timestamps, OHLC, tick volume, spread points and real volume when supplied by the broker.

## Historical news
The MetaTrader Python history collector does not pretend it has a complete historical economic-calendar dataset. News-event history must be supplied/validated separately before a news-filtered Strategy A backtest can be considered complete. `examples/historical_news_template.csv` defines the import shape.

## Next validation step
1. Run collector on the user's Windows/VPS MT5 demo terminal.
2. Run dataset audit.
3. Replay the normal Atlas strategy pipeline chronologically.
4. Apply A+ quality threshold and Supervisor gates.
5. Resolve fixed-2R / BE70 outcomes.
6. Produce per-symbol and aggregate reports, including 38.2-61.8 vs 61.8-78.6 Fibonacci segments.
