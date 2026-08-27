# Atlas Trading Expert v0.21.3 - HTF Alignment + H1 Fibonacci Gate Validation

## Scope
This checkpoint advances from v0.21.2 H1 real-data validation into downstream H4/H1 alignment and the first H1 Fibonacci gate validation. H4 and H1 remain hard-isolated; only their completed reports are compared downstream.

## Alignment finding and correction
The original `HTFAlignmentService` compared H4 effective direction directly with the H1 formal trend. Because H1 deliberately preserves its prior formal trend while an opposite reversal candidate develops, that comparator could theoretically approve stale alignment during an unresolved H1 reversal.

v0.21.3 adds coordinator-only guards:
- Any H1 phase containing `REVERSAL` returns `WAIT / H1_REVERSAL_STATE_UNRESOLVED` until H1 confirms or invalidates the reversal candidate.
- An H4 reversal-candidate phase returns `WAIT / H4_REVERSAL_STATE_UNRESOLVED` when H4 effective direction still equals the old formal trend.
- A separately confirmed H4 early/effective direction may still align downstream while formal H4 trend remains historical, preserving the trendline early-direction architecture.
- Ordinary H1 corrections remain alignment-eligible because Fibonacci and lower-timeframe monitoring are specifically designed to operate during correction context.

## EURUSD 2021 downstream replay
Using the v0.21.2 validated H1 seed and an independently bootstrapped H4 report stream:
- 2021-08-18 18:00 H1 enters bearish reversal candidate -> alignment returns WAIT.
- 2021-09-03 15:00 H1 bearish reversal correction is >=38.2% qualified -> alignment remains WAIT.
- 2021-09-29 10:00 H1 confirms the new bearish trend -> downstream alignment becomes `ALIGNED_BEARISH` through H4's independently confirmed early bearish/effective direction.
- No aligned state occurred while H1 remained a reversal candidate.

## Fibonacci findings and corrections
The Fibonacci engine correctly defined 78.6%+ as `STRUCTURE_RISK`, but still set `broad_m15_activation=True`. This violated the frozen 38.2%-78.6% broad-M15 activation window.

v0.21.3 fixes the gate:
- 38.2% <= retracement < 61.8%: broad M15 active.
- 61.8% <= retracement < 78.6%: broad M15 active, deep correction.
- retracement >= 78.6%: `STRUCTURE_RISK`, broad M15 disabled.
- Exact Fibonacci boundaries are normalized to prevent floating-point drift (e.g. mathematical 78.6% cannot fall into the sub-78.6 bucket).

Real EURUSD replay produced zero 78.6%+ broad-M15 activation violations.

## Open strategy decision - do not change silently
The current Fibonacci engine uses the **current H1 price** to decide whether broad M15 is active. During a qualified correction, price can cross 38.2%, begin reversing, then move back below 38.2%, causing broad-M15 activation to turn off even though H1's own `correction_qualified` state remains true.

Before freezing the Fibonacci-to-M15 handoff, decide explicitly whether:
1. **Current-position gate**: broad M15 is active only while current H1 retracement is physically between 38.2% and 78.6%; or
2. **Latched correction gate**: once the current H1 correction reaches >=38.2%, broad M15 remains awake while that correction/reversal sequence is active, until H1 rolls the impulse, invalidates structure, or reaches the >=78.6% risk condition.

This decision affects lower-timeframe entry timing and must be validated/backtested rather than inferred inside the implementation.

## Regression status
Full project suite: **130 passed, 0 failed**.

## Next implementation step
Resolve the current-position-vs-latched Fibonacci monitoring rule, then freeze the H1 Fibonacci handoff contract and proceed to M15 specialist/coordinator validation without allowing M15 to redefine H4/H1 structure.
