# Atlas Trading Expert v0.22.3 — Challenger Research Checkpoint

## Status
Research-only checkpoint. No live strategy rule changes from v0.22.2. The v0.22.2 control remains authoritative.

## Expanded evidence
The original 69 resolved Monday–Thursday review-ready events were supplemented with additional real GBPUSD active-window replay from January 2019 and July 2020. After enforcing the frozen Monday–Thursday calendar and global event deduplication, the combined resolved sample contains 91 events:

- 22 wins / 69 losses
- 24.18% win rate
- -25R gross
- -0.275R expectancy per review-ready event before costs
- EURUSD: 57 events, -18R, -0.316R/event
- GBPUSD: 34 events, -7R, -0.206R/event

These remain Coordinator READY_FOR_SUPERVISOR_REVIEW historical candidates, not reconstructed final executions; historical news, static-zone, live spread/slippage, and broker-specific execution gates are still incomplete.

## Challenger 1 — disable Triangle/Wedge
Rejected as a generalized rule.

On the original 69-event sample, removing Triangle/Wedge improved expectancy from -0.304R to -0.217R/event. However, additional GBPUSD active windows produced 5 Monday–Thursday Triangle/Wedge events with 2 wins, 3 losses, +1R total (+0.20R/event). Across the expanded 91-event sample, Triangle/Wedge contains 28 events, 6 wins, -10R (-0.357R/event), but the cross-regime reversal means the family cannot be disabled based on the initial sample alone.

Conclusion: retain Triangle/Wedge in the frozen discovery contract. Continue family-level monitoring rather than disabling it.

## Challenger 2 — Flag/Pennant stop geometry
Research hypothesis only; not promoted.

Across the expanded sample, Flag/Pennant has 46 events, 14 wins, -4R (-0.087R/event). A simple absolute stop-distance screen shows a potentially meaningful split:

- Flag/Pennant stop >=15 pips: 36 events, 14 wins, +6R, +0.167R/event
- Development years 2013–2017: 16 events, 7 wins, +5R, +0.313R/event
- Later 2018–2021 holdout: 20 events, 7 wins, +1R, +0.050R/event

The effect does not justify a fixed 15-pip production rule. A fixed pip threshold is symbol-specific and may proxy for market volatility, pattern scale, spread sensitivity, or structural noise. ATR-normalized tests were mixed: larger stop/ATR ratios improved the full sample, but later holdout performance was not robust enough to freeze a volatility threshold.

Conclusion: preserve this as a challenger hypothesis. Future tests should use a volatility-normalized structural-noise ratio and newer broker-native data rather than hard-code 15 pips.

## Small-sample families
Head & Shoulders and Channel each remain 0/6 in the expanded resolved sample. This is insufficient to disable either family. Impulse/Correction is 2/5 (+1R) but also too small for promotion.

## Decision
No strategy rule changes.

- Keep v0.22.2 strategy semantics as control.
- Reject immediate Triangle/Wedge disable as non-generalizing.
- Do not add a fixed minimum stop in pips.
- Preserve Flag/Pennant structural-scale filtering as a challenger for future volatility-normalized research.
- Continue historical static-zone/news reconstruction, newer broker-native MT5 replay, and additional symbols before any live-capital decision.

## Regression
166/166 tests pass unchanged.
