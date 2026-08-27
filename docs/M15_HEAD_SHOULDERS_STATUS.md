# M15 Head & Shoulders Agent - v0.8

Implemented pattern-specific Head & Shoulders / Inverse Head & Shoulders logic.

## Frozen behavior represented in code
- Activates only when H1 Fibonacci retracement is at least 38.2%.
- Requires correct prior-trend context: H&S after bullish trend for SHORT permission, inverse H&S after bearish trend for LONG permission.
- Validates left shoulder, head, right shoulder, neckline, configurable shoulder asymmetry, and minimum head prominence.
- A decisive M15 close through the neckline confirms the pattern.
- Does **not** import the Triangle/Wedge requirement to break the next structural S/R.
- Supports three independently testable entry modes:
  1. neckline breakout close,
  2. breakout plus confirmation candle,
  3. neckline retest/rejection.
- Does not chase breakouts that are already materially extended from the neckline; waits for retest instead.
- Retest mode may use the validated retest pivot as the structural stop anchor; otherwise the right shoulder is the default pattern stop anchor.
- Final stop adds the standard configurable spread/ATR/wick/tick buffer.
- False-break and stale-entry states are explicit.

Exact thresholds remain calibration parameters and must be backtested by symbol.
