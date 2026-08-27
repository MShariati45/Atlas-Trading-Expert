# Atlas Structure V2 Teaching Model - v0.24.6 Research Only

This module is deliberately isolated from execution and the existing shadow supervisor. It is a teaching/research layer for H4, H1, M15, and future M5.

## Core doctrine

1. Trend is hierarchical price structure: bullish = meaningful HH/HL; bearish = meaningful LL/LH.
2. An impulse is a sustained structural leg and may contain opposite-colored candles, minor swings, consolidations, and wicks.
3. Fibonacci 38.2% is only a candidate-depth gate. It cannot promote a pivot by itself.
4. A strategic correction must be a developed countertrend movement: meaningful depth plus multi-candle/body development. One wick-dominated candle is rejected.
5. Strategic pivots are the broader-perspective anchors. Minor pivots between them remain internal.
6. Two or more coherent HLs (bullish) or LHs (bearish) provide trendline evidence. Exact line contact is not mandatory; geometry is supporting evidence.
7. A range inherits the previous dominant trend until the strategic control pivot is decisively broken and opposite structure develops.
8. A control-pivot break is CHoCH/transition evidence, not automatic trend reversal. Follow-through closes and a meaningful opposite pivot are required before a new trend is confirmed.
9. The philosophy is identical but independently evaluated on H4, H1, M15, and future M5. No timeframe may inherit another timeframe's pivots or trend.

## First labelled benchmark

XAUUSD H4: bullish active impulse expected approximately 4311 -> 4630. The reaction after the ~4527 high that only approached the 38.2% retracement through a wick-dominated H4 event is labelled internal, not a completed strategic correction. Therefore the impulse origin must not reset to ~4450 solely because of that reaction.

## Safety

The research runner is read-only. It reads completed MT5 candles, writes only `runtime/structure_v2_research.json`, and does not mutate production/shadow structure state or place orders.
