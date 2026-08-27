# Atlas v0.3 - H1 Structure + Fibonacci Status

Implemented in this checkpoint:

- Stateful H1 strategic structure engine using the same multi-candle strategic-leg logic as H4.
- H1 remains independent from H4 and reports ALIGNED, CORRECTIVE_AGAINST_H4, TRANSITIONING, or UNKNOWN.
- H1 emits Fibonacci eligibility and M15 eligibility without using Fibonacci to determine trend.
- Fibonacci Retracement Engine consumes a validated H1 impulse and measures 23.6, 38.2, 50, 61.8, 78.6 and 100 percent levels.
- Below 38.2 percent, Flag/Pennant receives early access while the broader M15 layer remains inactive.
- At or above 38.2 percent, broader M15 activation becomes true and new Flag/Pennant discovery is disabled.
- At 78.6 percent or deeper, Fibonacci reports STRUCTURE_RISK; it does not independently change H1 trend.
- Dashboard now reads a state.json contract rather than hard-coding all summary values in HTML.

Not yet implemented:

- Historical auto-seeding/discovery of H1 strategic state from raw MetaTrader history.
- Live MetaTrader price/candle bridge.
- M15 specialist algorithms.
- Production persistence (Redis/Postgres).
