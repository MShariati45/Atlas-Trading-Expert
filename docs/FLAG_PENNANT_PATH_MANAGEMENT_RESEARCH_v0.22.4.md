# Atlas v0.22.4 — Flag/Pennant Path & Management Research

## Status
Research-only checkpoint. No live strategy-rule changes from v0.22.3. The fixed gross 2R baseline remains authoritative.

## Sample
Expanded v0.22.3 Flag/Pennant sample: 46 Monday–Thursday, globally deduplicated, resolved review-ready events across EURUSD/GBPUSD, 2014–2021.

Baseline: 14 wins / 32 losses, 30.43% win rate, -4R gross, -0.087R/event.

## Losing-trade favorable excursion
Of 32 baseline losses:
- 4 reached +1R on a prior M15 bar and later hit the original -1R stop.
- 1 of those reached at least +1.25R (maximum observed losing-trade MFE ~1.48R).
- 0 reached +1.5R before stopping.
- 15 reached at least +0.5R before stopping (plus one same-bar ambiguous 0.5R/SL path).

Loss MFE distribution:
- <0.25R: 13
- 0.25–0.50R: 3
- 0.50–0.75R: 9
- 0.75–1.00R: 3
- 1.00–1.25R: 3
- 1.25–1.50R: 1
- >=1.50R: 0

## Counterfactual beyond the fixed 2R target
The current live baseline exits at +2R, so a trade cannot actually reach +2.5R and later stop out. For research only, the same entries were replayed with the 2R TP removed while preserving the original structural stop for up to 480 M15 bars.

Among the 46 Flag/Pennant trades:
- 8 reached +2R and later returned to the original -1R stop.
- 6 reached +2.5R and later returned to the original -1R stop.
- 5 reached +3R and later returned to the original -1R stop.
- 2 reached +4R and later returned to the original -1R stop.
- 1 reached +5R and later returned to the original -1R stop.

All six +2.5R-then-stop cases were baseline 2R winners under the current Atlas rule.

## Winners that pulled back and recovered to 2R
Among the 14 baseline 2R winners, after first reaching +1R and before first reaching +2R:
- 11 pulled back to <= +0.75R and then recovered to +2R.
- 7 pulled back to <= +0.50R and then recovered to +2R.
- 6 pulled back to <= +0.25R and then recovered to +2R.
- 2 pulled back below entry (negative R) without hitting the original stop, then recovered and reached +2R.
- 0 pulled back to <= -0.25R before recovering to +2R.

This is why aggressive early trailing can destroy valid winners.

## Management challengers
All variants are research-only and use M15 OHLC replay. Trailing levels are updated from prior completed-bar excursion to avoid assuming intrabar high/low order.

### Baseline
Fixed TP +2R, original structural SL -1R:
- Total: -4R across 46, -0.087R/event.

### Fixed breakeven after +1R
Keep TP +2R; after +1R, move stop to 0R:
- Total: -4R, exactly equal to baseline in this sample.
- It saves the four losses that reached +1R, but sacrifices enough recovering winners to offset the benefit.

### Dynamic 1R trailing distance activated at +1R
Keep TP +2R; once +1R is reached, trail one R behind peak:
- Total: approximately -12.00R, -0.261R/event.
- Clearly worse. It cuts too many eventual 2R winners during normal pullbacks.

### Remove 2R TP; activate 1R trailing distance after +2R
- Total: approximately -5.06R, -0.110R/event.
- Slightly worse than baseline.

### Remove 2R TP; wait for +2.5R, then trail one R behind peak
- Full sample: approximately -2.29R, -0.050R/event, superficially better than baseline.
- 2013–2017 development: +6.64R vs +1R baseline.
- 2018–2021 holdout: -8.93R vs -5R baseline.
- Therefore the improvement does not generalize and must not be promoted.

## Structural-scale subset (stop >=15 pips, research only)
36 trades, baseline 14 wins / 22 losses, +6R total (+0.167R/event).

Management comparison:
- Baseline fixed 2R: +6R.
- Breakeven after +1R: +5R.
- Dynamic 1R trail from +1R with 2R TP: about -3.09R.
- Remove 2R TP; trail 1R after +2R: about +4.94R.
- Remove 2R TP; trail 1R after +2.5R: about +7.71R overall, but later 2018–2021 holdout falls from +1R baseline to about -2.93R.

Again, no management challenger is robust enough to freeze.

## Pattern detail
- Bull Flag: 26 events, 9 wins, +1R total.
- Bear Flag: 16 events, 4 wins, -4R total.
- Bull Pennant: 3 events, 0 wins, -3R total.
- Bear Pennant: 1 event, 1 win, +2R total.

Pennant sample sizes are too small for separate conclusions.

## Decision
Do not add a 1R trailing rule yet.

The data supports two facts:
1. Four losing Flag/Pennant trades gave back >=1R to the original stop, so loss-protection research is justified.
2. Many eventual winners also make substantial pullbacks after +1R, so an aggressive early trail damages expectancy.

The best next test is broker-native, out-of-sample Flag/Pennant path replay on newer data, comparing a small predeclared management matrix rather than optimizing thresholds repeatedly:
- Control: fixed 2R.
- BE at +1R.
- 1R trail activated at +2R with no 2R TP.
- 1R trail activated at +2.5R with no 2R TP.

No live rule changes until a challenger beats the control in later out-of-sample data after costs.
