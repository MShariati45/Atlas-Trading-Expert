# M15 Flag / Pennant Agent - v0.6 status

Implemented as a continuation specialist with Atlas-specific early Fibonacci access.

## Frozen behaviors implemented
- New pattern discovery is allowed only while H1 retracement is below 38.2%.
- A pattern already mature before 38.2% may continue to resolution after the threshold is crossed.
- Flagpole must be strong relative to M15 ATR and aligned with H4/H1 permitted direction.
- Consolidation must remain shallow (<38.2% of the flagpole in the baseline policy) and time-limited.
- Supports FLAG and PENNANT classifications.
- A full M15 close through the continuation boundary is required for VALID_TRIGGER.
- Stop is anchored beyond the consolidation invalidation extreme with a configurable spread/ATR/wick/tick buffer.
- Classical flagpole projection is calculated as context only; Atlas live target remains fixed 2R.
- Trigger freshness is tracked and stale triggers are not chaseable.

## Still pending
- Automated geometric derivation of flag/pennant boundaries from raw MT5 candles and validated pivots.
- Symbol-specific calibration of ATR/pole/consolidation thresholds.
- Retest/confirmation-candle entry variants for backtest comparison.
