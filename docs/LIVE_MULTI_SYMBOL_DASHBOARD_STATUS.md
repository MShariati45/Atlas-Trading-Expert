# Atlas v0.14 - Live Multi-Symbol Observation Dashboard

Status: IMPLEMENTED (READ ONLY)

## What is live when run beside MetaTrader 5
- MT5 terminal/account health
- account balance/equity/margin metadata
- open positions
- per-symbol bid/ask and spread
- persisted H4/H1 strategic state from completed candles
- H4/H1 alignment
- H1 Fibonacci retracement depth and zone
- M15 activation state (Flag/Pennant early access vs broad M15 eligibility)
- coordinator/supervisor observation status
- state-change highlighting

## What is deliberately not claimed live yet
- No orders are sent.
- M15 pattern specialists are not yet continuously fed full live M15 pattern state in this launcher; v0.14 displays eligibility/scanning state truthfully rather than inventing triggers.
- News Guard is shown NOT_CONFIGURED_LIVE until a live economic-calendar source is connected.
- Static Zones are shown NOT_CONFIGURED_LIVE until the cached D1/H4 zone detector is wired to live history.

## Runtime model
- First connection bootstraps H4/H1 from completed history.
- Persisted cursors prevent full rescans.
- Subsequent refreshes process only newly closed H4/H1 bars.
- Dashboard refresh can run every few seconds without forcing full structural analysis.
- The launcher has no execution path and sets execution_enabled=false.

## Next milestone
Wire live M15 bars into all six specialist engines and connect live Static Zone + News Guard services, still in read-only/paper-signal mode.
