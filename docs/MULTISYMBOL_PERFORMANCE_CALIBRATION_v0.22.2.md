# Atlas v0.22.2 - Multi-symbol performance calibration checkpoint

## Scope

This checkpoint does **not** change the frozen v0.22.1 H4/H1/Fibonacci/M15 discovery or Supervisor rules. It adds historical calibration evidence only.

Real-data source in the package: EURUSD and GBPUSD M15 datasets spanning 2013-2021. H1/H4 are reconstructed from M15 for each replay. Every replay bootstraps structure only from history before the scored window, then applies the normal H4/H1 alignment and Fibonacci permissions before M15 discovery.

The scored objects below are Coordinator packages in `READY_FOR_SUPERVISOR_REVIEW`, not claims that every package would have been historically executed. Historical news, static-zone, live-spread/slippage and broker-specific execution gates are not reconstructed in this calibration. The Monday-Thursday Atlas entry restriction is applied in the combined metrics below.

## Sample

Two separated-window batches were combined and deduplicated by symbol + event ID.

- 69 resolved Monday-Thursday review-ready events
- 16 fixed-2R winners
- 53 stop losses
- Win rate: 23.19%
- Gross result: -21R
- Expectancy: -0.304R per resolved event
- Long: 35 events, 8 wins, -11R
- Short: 34 events, 8 wins, -10R

At a fixed +2R / -1R payoff, breakeven win rate before costs is 33.33%. The observed sample is below that requirement.

## Pattern-family evidence

- Flag/Pennant: 34 events, 11 wins, 23 losses, -1R total, -0.029R/event. This is the strongest large-sample family but is not yet demonstrably positive after costs.
- Triangle/Wedge: 23 events, 4 wins, 19 losses, -11R total, -0.478R/event.
- Head & Shoulders: 4 events, 0 wins, -4R.
- Channel: 4 events, 0 wins, -4R.
- Impulse/Correction: 4 events, 1 win, -1R.

Pattern subtypes remain too small or unstable for live inclusion/exclusion decisions. Bull Flag was +2R over 16 samples but varied substantially by year; it must not be promoted based on that small, non-stable subset.

## Fibonacci context

- ACTIVE_SHALLOW: 30 events, 9 wins, -3R total (-0.10R/event)
- ACTIVE_LATCHED_RECOVERY: 31 events, 6 wins, -13R total (-0.419R/event)
- ACTIVE_PRIMARY_CORRECTION: 8 events, 1 win, -5R total (-0.625R/event)

This is evidence for future research only. The v0.21.4 latch rule is not changed here.

## Stop distance

Across the combined review-ready sample, normal stop distances were generally in the tens of pips. The earlier 725.77-pip outlier occurred on Friday and is blocked by the frozen Atlas Monday-Thursday execution rule. Wide stops still occur in volatile regimes and should continue to be logged. No arbitrary maximum-stop rule is introduced from this sample.

## Trade-management diagnostic

Of 53 losing trades, 13 first reached at least +1R and 5 reached at least +1.5R before ultimately stopping. A simple hypothetical break-even move after +1R would reduce losses but still leave the aggregate sample negative. Therefore no break-even or partial-profit rule is added at this checkpoint.

## Decision

The M15 discovery/handoff contract remains a frozen candidate, but the complete strategy is **not profitability-validated and not production-ready**. Current evidence does not justify live capital deployment or pattern-rule loosening.

The next research phase should preserve v0.22.1/v0.22.2 as the control and run explicit challenger experiments, starting with:

1. Triangle/Wedge as a research-only disable/holdout candidate because its larger sample is materially negative.
2. Flag/Pennant as the first family for broader out-of-sample validation because it is closest to breakeven without filtering.
3. Separate evaluation of entry model (immediate break, confirmation candle, retest) using the metadata already tracked by specialists.
4. Static-zone and news historical reconstruction before interpreting review-ready packages as executable trades.
5. Broader symbols and newer broker-native MT5 history before any live-risk decision.

No challenger becomes a live rule without out-of-sample validation and explicit owner approval.
