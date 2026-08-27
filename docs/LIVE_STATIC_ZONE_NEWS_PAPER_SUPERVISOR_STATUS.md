# Atlas v0.16 - Live Static Zones + News Guard + Paper Supervisor

Status: read-only / paper-decision milestone. No order execution is enabled.

## Added
- Deterministic completed-candle D1/H4 static-zone builder using confirmed reaction swings and ATR-aware clustering.
- Cached target-path assessment for the fixed 2R objective.
- Provider-neutral scheduled-news adapter contract.
- JSON news-calendar adapter for development/demo use.
- Tri-state live news gate: CLEAR / BLOCKED / DATA_UNAVAILABLE. Missing news data is never treated as safe.
- End-to-end paper Supervisor pipeline from M15 Coordinator package through calendar, static-zone, market-cost, news, risk, freshness, and structural-stop gates.
- Dashboard integration for PAPER_APPROVE / PAPER_WAIT / PAPER_REJECT and supporting reasons.

## Important safety behavior
If a required news provider is not configured or fails, `news_ok=None`; the Supervisor returns WAIT rather than assuming there is no event risk.

Static zones are built from completed D1/H4 bars and cached per symbol. They should be refreshed when price materially approaches/breaks/invalidates a cached zone; v0.16 establishes the live derivation and cache boundary, while event-triggered selective refresh remains a subsequent optimization.

## Execution
Disabled. v0.16 is for observation and paper decisions only.
