# Atlas M15-First Profile v0.23.6

This checkpoint preserves the final 2025-08-19 to 2026-08-19 pair-by-pattern demo candidate and removes the obsolete original Channel Breakout implementation.

## Active symbols
EURUSD, USDJPY, USDCAD, XAUUSD. GBPUSD is not in the active package configuration.

## Channel rule
`CHANNEL_BOUNDARY_REJECTION` is the sole active channel pattern. The previous `CHANNEL_BREAKOUT` pattern identifier and breakout/retest state machine are removed from active strategy code.

## Pair-pattern permissions
- EURUSD: Impulse/Correction, Triangle/Wedge.
- USDJPY: Channel Boundary Rejection, Flag/Pennant, Head & Shoulders, Triangle/Wedge.
- USDCAD: Channel Boundary Rejection, Multiple Top/Bottom, Triangle/Wedge.
- XAUUSD: Channel Boundary Rejection, Flag/Pennant, Head & Shoulders, Impulse/Correction, Multiple Top/Bottom, Triangle/Wedge.

Risk, session, pair-specific HTF modes and target assignments remain frozen. H4 downstream context uses the H4 agent effective direction (formal trend unless its independently validated early trendline reversal is active). Fibonacci remains informational only.
