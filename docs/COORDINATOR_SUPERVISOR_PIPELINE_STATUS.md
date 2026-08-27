# Atlas v0.10 Coordinator + Supervisor Pipeline

Implemented:
- M15 report normalization across all specialists.
- Opposite-direction actionable evidence is labeled conflict, never averaged.
- Same-event reports can be deduplicated using event_id, trigger time, or identical entry reference.
- Separate same-direction events are retained as independent confirmation.
- Early Multiple Top/Bottom signals still wait for independent Impulse/Correction confirmation.
- Deterministic Supervisor hard gates: failed = REJECT, pending = WAIT, all passed = APPROVE.
- Daily risk ledger: 1.0% max, 2 trades/day, 0.5% default, one trade per symbol/day.
- Opening any trade places Supervisor in TRADE_FOCUS.
- Symbol lock remains after the position closes until next-day reset.
- Two opened trades consume the daily trade allowance even if later closed or moved to breakeven.

Still external inputs at this milestone:
- Static-zone gate value.
- News gate value.
- Spread/slippage gate value.
- Live broker fill state.
These will be wired to their live service modules in subsequent milestones.
