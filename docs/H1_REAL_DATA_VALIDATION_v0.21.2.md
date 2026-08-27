# Atlas Trading Expert v0.21.2 - H1 Real-Data Validation

## Scope
Validated the independent H1 Structure Agent against real EURUSD H1 OHLC history while preserving H4/H1 hard isolation.

## Data source
Public EURUSD H1 CSV from `komo135/forex-historical-data` (GitHub, Apache-2.0), covering 2012-11-16 through 2022-03-04. This is used only as a structural replay dataset; final broker-specific validation must still be repeated with the MetaTrader 5 historical collector.

## Baseline finding
The v0.21.1 H1 agent passed synthetic isolation tests but exposed two structural defects on real replay:

1. A close through the validated H1 control pivot produced a transient reversal-candidate phase, but later bars could return the agent to the old trend without completing or invalidating a reversal state machine.
2. A >=38.2% qualified correction was not rolled into the new strategic origin/control pivot on the actual continuation BOS candle; validation was delayed to a later bar.

## v0.21.2 correction
- Added a persistent opposite-direction reversal candidate state.
- Formal H1 trend remains unchanged at the first control-pivot break.
- The reversal candidate tracks its own origin, extending endpoint, correction extreme, correction depth, and qualification state using H1 data only.
- A new trend is confirmed only after the opposite impulse develops a >=38.2% correction and then continues through its prior candidate extreme.
- A qualified continuation correction now rolls the strategic origin/control pivot on the same BOS bar that validates it.
- Added explicit audit codes including `REVERSAL_CANDIDATE`, `REVERSAL_CORRECTION_QUALIFIED`, `NEW_TREND_CONFIRMED`, `REVERSAL_CANDIDATE_INVALIDATED`, and `VALIDATED_BY_CONTINUATION_BOS`.
- H4-prefixed/cross-timeframe input remains forbidden.

## EURUSD H1 replay checkpoint
Spring 2021 bullish seed:
- Bullish strategic origin: 2021-03-31 07:00, 1.17041
- Bullish strategic endpoint: 2021-05-25 15:00, 1.22664
- Bullish control pivot break / bearish reversal candidate: 2021-08-18 18:00
- Bearish reversal correction >=38.2% qualified: 2021-09-03 15:00 (about 40.69%)
- New bearish H1 trend confirmed by continuation: 2021-09-29 10:00
- New bearish strategic origin/control pivot: 1.19091
- New bearish endpoint at confirmation: 1.16566
- Later bearish continuation BOS/control roll: 2021-11-05 14:00

By the end of the available dataset (2022-03-04), the H1 state remained BEARISH and continued to update strategic origin/control and endpoint without H4 input.

## Regression result
Full project suite after the H1 correction: **123 passed, 0 failed**.

## Remaining validation before Fibonacci
1. Repeat the same H1 replay using broker-native MT5 EURUSD H1 history when a connected MT5 terminal is available.
2. Compare completed independent H4 and H1 reports only downstream through the alignment service.
3. If alignment behavior is clean, proceed to H1 Fibonacci validation using only the validated H1 strategic impulse.
