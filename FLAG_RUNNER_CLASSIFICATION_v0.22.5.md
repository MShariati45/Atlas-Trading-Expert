# Atlas v0.22.5 - Flag/Pennant Runner Classification Research

Research-only checkpoint. No live strategy rules changed from v0.22.4 / v0.22.3 control behavior.

## Sample
- 46 globally deduplicated, Monday-Thursday, resolved Flag/Pennant review-ready events.
- 14 fixed-2R winners, 32 losses.
- Baseline fixed-2R result: -4R.

## Runner extension among baseline winners
Using the same entry and original structural stop, and examining continuation after the first 2R touch:
- 11 of 14 winners extended to at least 2.5R.
- 10 of 14 extended to at least 3R.
- 7 of 14 extended to at least 4R.
- 6 of 14 extended to at least 5R.

Seven winners eventually revisited the original-stop region in the research continuation path after 2R, reinforcing that substantial post-2R give-back exists.

## Entry/by-2R characteristics
Among 2R winners, 3R+ runners tended to have:
- lower M15 ATR at entry than non-runners,
- slightly higher stop/ATR structural scale,
- more shallow-Fibonacci context,
- more bullish Flag examples,
- somewhat faster resolution to 2R.

However, the sample is small and these relationships were not stable enough for promotion.

## Predeclared conditional management tests
Control: fixed 2R on all trades.
Challenger action for selected 2R winners: remove fixed TP at 2R and trail 1R behind the best price thereafter.

Full sample / development / later holdout results:
- All 2R winners trailed: -5.61R overall vs -4R control; later holdout -8.62R vs -5R.
- Bull Flag only: -6.11R overall; later holdout -7.87R.
- Active shallow only: -4.89R overall; later holdout -7.90R.
- Fast to 2R (<=30 M15 bars): -7.13R overall; later holdout -7.49R.
- Bull + shallow: -5.39R overall; later holdout -7.14R.

None beat the fixed-2R control on the later 2018-2021 holdout.

## Decision
Do not add conditional post-2R trailing to Atlas yet. Runner behavior is real, but current observable features do not robustly identify runners out-of-sample. Preserve fixed 2R as the control. Revisit only with newer broker-native MT5 data and a predeclared classifier/management test.
