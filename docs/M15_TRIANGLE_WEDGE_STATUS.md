# M15 Triangle & Wedge Engine Status - v0.7

Implemented pattern-specific Atlas behavior for ascending, descending and symmetrical triangles plus rising and falling wedges.

Key rules:
- Broad M15 activation begins only at H1 Fibonacci retracement >= 38.2%.
- Pattern maturity requires at least two meaningful reaction highs and two meaningful reaction lows.
- A full M15 close outside the relevant pattern boundary is only `BOUNDARY_BREAK_CONFIRMED`.
- No entry candidate is emitted until the first meaningful validated M15 resistance (long) or support (short) beyond the boundary is also closed through.
- A single strong candle may satisfy both gates if it objectively closes beyond both independent levels.
- Closing back inside the formation before the structural S/R break invalidates the breakout as a false break.
- Retest is tracked as optional context, not a mandatory entry condition.
- Stop proposals use a structural invalidation anchor plus the shared spread/ATR/wick/tick buffer model.
- This extra S/R-break rule is isolated to Triangle/Wedge and is not generalized to other pattern agents.
