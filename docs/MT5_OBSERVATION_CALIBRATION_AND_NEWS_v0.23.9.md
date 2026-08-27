# Atlas v0.23.9 - MT5 Observation Calibration & Live News Readiness

## Purpose
This checkpoint advances the demo workflow without enabling order transmission.

## Broker cost calibration
`run_mt5_broker_calibration.bat` samples live bid/ask spreads for EURUSD, USDJPY, USDCAD and XAUUSD. It writes:
- `runtime/broker_spread_samples.csv`
- `runtime/broker_calibration_summary.json`

The collector is read-only. It does **not** estimate or claim real slippage because slippage can only be measured against actual submitted/fill prices. No limits are activated automatically from the collected sample.

Recommended collection: run across multiple market sessions/days before selecting production spread limits.

## Live news
Atlas uses a provider-neutral scheduled-news JSON contract. For paper-supervisor readiness the live file must include trustworthy source freshness metadata:
- `generated_at_utc`
- `valid_until_utc`
- `events`

`run_live_news_refresh.bat` can fetch such a schedule from a configured trusted/licensed JSON endpoint using `ATLAS_NEWS_URL` and, if needed, `ATLAS_NEWS_BEARER_TOKEN`. No AI call is involved.

Atlas refuses to mark news ready if source freshness metadata is missing or the schedule does not remain valid for at least six hours.

## Safety
- MT5 order execution remains hard locked.
- Spread collection is observation only.
- Slippage remains pending until an explicitly approved demo execution phase.
- News data unavailable/stale => Supervisor WAIT.

## Paper-supervisor promotion
`ready_for_paper_supervision` requires all read-only preflight checks, fresh live news, and an explicitly `APPROVED` broker-cost policy covering all four symbols. The cost policy is never generated/approved automatically.

The default high-impact-news blackout is 120 minutes before the scheduled event, matching the conservative 1-2 hour Atlas rule.
