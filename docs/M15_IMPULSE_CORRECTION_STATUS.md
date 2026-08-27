# M15 Impulse & Correction Agent - v0.4 status

Implemented as an incremental, persistent M15 structure engine.

## Frozen behavior now encoded
- Multi-candle structure; individual candle colour does not create a new impulse/correction.
- Uses a seeded validated M15 control pivot and endpoint rather than rescanning history on every bar.
- Bearish-to-bullish reversal: close above last validated LH = CHoCH only; then require new HH, meaningful pullback forming HL, and BOS close above the new HH before VALID_TRIGGER.
- Bullish-to-bearish reversal mirrors the above.
- CHoCH can never directly emit a trade trigger.
- Higher-timeframe permitted direction is a hard gate.
- Stop anchor is the newly formed HL/LH supporting BOS.
- Dynamic stop buffer takes the maximum of configurable spread, ATR, wick-profile, and tick-size components.
- Trigger freshness is tracked and can become STALE after a configurable number of closed M15 bars.
- Exact buffer coefficients remain calibration/backtest parameters, not frozen market truths.

## Still deliberately deferred
- Historical auto-discovery of the initial validated M15 strategic structure.
- Pair-specific learned wick distributions and ATR calibration database.
- Net 2R/static-zone checks (Supervisor responsibility).
- Coordination with Multiple Top/Bottom early reversal messages (Coordinator phase).
