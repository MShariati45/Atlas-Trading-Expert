# Atlas v0.23.5 Deep Technical Audit

## Scope
Package-wide audit after v0.23.4 Boundary-Rejection-only cleanup.

## Corrections made
1. Root pytest discovery is constrained to `tests/`, preventing standalone historical research scripts with machine-specific paths from being collected as production tests.
2. Package version metadata updated to 0.23.5.
3. Legacy dashboard default watchlist now uses the active four-symbol strategy profile and passes that profile to M15 specialists.
4. Paper Supervisor target construction now honors `package.target_r` instead of hard-coding 2R. This preserves 3R Channel Boundary Rejection for USDCAD and XAUUSD.
5. Explicit optional AI usage policy added: disabled by default, event-driven-only, cache-aware, with daily/monthly call caps.

## AI cost architecture
Current strategy execution and observation path uses no LLM/API. H4/H1 structure, M15 specialists, pattern gate, static zones, market costs, news gating, risk and Supervisor logic are deterministic. Provider adapters are isolated and intentionally unimplemented. Therefore the current demo observer has zero paid AI API consumption.

Future AI use must remain advisory and pass `AIUsagePolicy` before any provider call is wired. Default limits are 8 calls/day, 120 calls/month, 24-hour cache TTL, with AI disabled until explicitly enabled.

## Demo boundary
No order transmission is enabled by the demo observer or demo validator. MT5 order methods remain isolated in the execution bridge for a later explicitly approved execution stage.
