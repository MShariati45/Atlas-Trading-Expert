# Atlas v0.21.8 - Real M15 History Replay Checkpoint

## Scope
No strategy code changes from v0.21.7. This checkpoint adds empirical replay evidence from real historical M15 candles and preserves the full 160/160 regression suite.

## Data
Source: jaxontn/historical-Data GitHub CSVs.

### EURUSD window A
- 2021-05-01 through 2021-06-15 06:00 UTC
- 3,012 M15 candles
- 950 M15 candles eligible after real H4/H1 alignment and Fibonacci gating
- Coordinator: 926 collecting/no actionable, 12 ready-for-Supervisor bars, 12 waiting-for-confirmation bars
- 8 unique actionable specialist events:
  - Head & Shoulders VALID_TRIGGER: 2
  - Impulse/Correction VALID_TRIGGER: 2
  - Channel VALID_TRIGGER: 1
  - Multiple Top/Bottom EARLY_REVERSAL_CANDIDATE: 3
- No duplicate, conflict, or independent-confirmation events in this window
- Structural stop distance across unique events: median ~14.1 pips, mean ~27.1 pips, max ~91.4 pips
- The 91.4-pip outlier is auditable and is not silently altered. It requires additional evidence before introducing a deterministic max-stop-distance rule.

### EURUSD window B
- 2020-09-01 through 2020-10-16
- 3,168 M15 candles
- 1,028 eligible M15 candles
- 5 unique actionable events:
  - Channel VALID_TRIGGER: 2
  - Head & Shoulders VALID_TRIGGER: 3
- Stop distance range ~9.4 to 13.9 pips
- No duplicates, conflicts, or independent confirmations observed

### GBPUSD window
- 2021-05-01 through 2021-06-15 06:00 UTC
- 3,012 M15 candles
- 125 eligible M15 candles
- One Multiple Top/Bottom EARLY_REVERSAL_CANDIDATE
- No Supervisor-ready trigger in this sampled window

## Key conclusions
1. The live M15 runtime remains highly selective on real history; it does not manufacture constant setups.
2. Real H4/H1/Fibonacci permissions were used ahead of M15 rather than forcing a constant direction.
3. Impulse/Correction, Head & Shoulders, Channel, and Multiple Top/Bottom have now appeared naturally in at least one sampled real-history window.
4. Flag/Pennant and Triangle/Wedge did not produce a real actionable trigger in the sampled windows. Their synthetic contract tests remain valid, but real-history coverage is insufficient to freeze them.
5. No duplicate/conflict/independent-confirmation event occurred in the sampled windows, so those coordinator behaviors remain covered by regression tests rather than empirical history so far.
6. No strategy thresholds were loosened merely to increase trigger count.

## Freeze status
- Upstream H4/H1/Fibonacci contract: unchanged.
- M15 Coordinator/Supervisor contracts: still valid.
- Full M15 specialist layer: NOT YET FROZEN because Flag/Pennant and Triangle/Wedge lack representative real-history actionable examples.

## Next step
Run targeted real-history discovery/validation for Flag/Pennant and Triangle/Wedge (EURUSD first, then GBPUSD), recording candidate formation, maturity, breakout/retest state, rejection reason, and whether conservative discovery is suppressing valid textbook structures. Do not loosen geometry or confirmation rules without identified false-negative examples and explicit review.
