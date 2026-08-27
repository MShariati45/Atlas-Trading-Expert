# Atlas v0.24.21 - News Readiness Hardening

This checkpoint advances staging integration without changing trading strategy.

## Change
`StagingReadiness` no longer treats the mere presence of `runtime/news_events.json` as market-open readiness. It now validates the live-news runtime through the strict scheduled-news provider and requires:

- fresh schedule metadata with at least six hours remaining validity;
- source provenance;
- USD/EUR/CAD/JPY coverage for the four-symbol watchlist;
- successful provider parsing.

A missing, stale, incomplete, or malformed news file therefore remains fail-closed and cannot make `market_open_ready` true.

## Safety
- Demo execution remains locked by default.
- No real-money execution is enabled.
- No trading strategy rules were changed.
- No AI calls are required for news ingestion.

## Next Windows step
Run `run_official_four_currency_news_refresh.bat`, then `run_staging_readiness.bat`. Market-open readiness should only turn true if the official-source news bundle validates at run time. Broker-cost calibration and fresh MT5 preflight remain separate required demo gates.
