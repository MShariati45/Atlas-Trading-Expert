# Atlas Trading Expert v0.21.4 - H1 -> Fibonacci -> M15 Handoff Freeze Candidate

## Scope
This checkpoint validates that long historical context does not leak obsolete H1 impulses into the live downstream handoff, and resolves the open 38.2% current-position-vs-latched M15 activation decision.

## Live/latest H1 impulse validation
A real EURUSD H1 replay was run from the validated spring-2021 seed through the end of the available dataset on 2022-03-04.

At the end of replay, the active H1 state was:
- Trend: BEARISH
- Strategic origin/control pivot: 2022-03-02 18:00, 111434
- Strategic endpoint: 2022-03-04 15:00, 108852
- Current correction maximum: about 31.49%
- Correction qualified: false

This confirms that the 2021 seed is historical context only. The active H1 structure rolled forward multiple times and the final Fibonacci handoff used only the latest strategic origin and endpoint.

## Frozen-candidate latch rule
Broad M15 activation now follows the H1 structural correction state rather than only the instantaneous current-price retracement:

1. Before H1 has ever qualified the active correction at 38.2%:
   - below 38.2%: no broad M15; only existing flag/pennant early-access logic may operate.
2. Once H1 correction_qualified becomes true (>=38.2% reached):
   - broad M15 remains active even if price recovers back to a current retracement below 38.2%.
   - new flag discovery remains disabled after the broad-M15 latch has been triggered.
3. The latch resets when H1 validates/rolls to a new strategic impulse because H1 correction_qualified and correction_depth reset.
4. If the active H1 correction reaches >=78.6% at any point, STRUCTURE_RISK is persistent for that impulse and broad M15 remains blocked until H1 resets/rolls the structure.
5. Fibonacci still cannot determine H1 trend, origin, endpoint, or correction qualification. Those are supplied by the H1 Structure Agent.

## Real replay observations
On the 2021-05-25 through 2022-03-04 EURUSD H1 replay:
- 1,036 H1 bars occurred where a correction had already qualified >=38.2% but current price had recovered to <38.2%. These are exactly the bars the former current-position gate would have switched broad M15 off; the latched model keeps M15 awake.
- 1,159 H1 bars were under persistent >=78.6% structure-risk state and correctly kept broad M15 blocked until the H1 structure reset.
- The final dataset state was a fresh bearish impulse with a 31.49% unqualified correction, so broad M15 was correctly off at the endpoint of the replay.

## Regression status
Full suite: 134 passed, 0 failed.

## Next step
Treat this as the H1 -> Fibonacci -> M15 handoff freeze candidate. Next validate the M15 specialist/coordinator layer against this contract:
- specialists receive permitted direction and activation context only;
- specialists cannot alter H4/H1 structure or Fibonacci anchors;
- coordinator normalizes simultaneous M15 evidence, conflicts, duplicates, freshness, and confirmation before Supervisor review.
