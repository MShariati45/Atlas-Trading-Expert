# Atlas Trading Expert v0.21.5
## M15 Specialist / Coordinator Handoff Validation

### Scope
This checkpoint validates the M15 specialist orchestration layer against the frozen-candidate v0.21.4 H1 -> Fibonacci -> M15 contract. H4, H1, and Fibonacci strategy logic are unchanged.

### Defects found and corrected
1. **Instantaneous Fib percentage was being used as the M15 runtime permission.**
   - This could wake broad specialists below 38.2% or re-enable new Flag/Pennant discovery during a latched recovery below 38.2%.
   - The runtime now consumes explicit Fibonacci permissions: `broad_m15_activation`, `new_flag_discovery_allowed`, and `structure_risk`.

2. **Broad specialists could influence the Coordinator during the shallow Flag-only phase.**
   - The Coordinator now receives an explicit eligible-agent set.
   - Below the 38.2% handoff, only Flag/Pennant can be actionable.
   - Once broad M15 is active, Impulse/Correction, Multiple Top/Bottom, Triangle/Wedge, Head & Shoulders, and Channel become eligible.
   - A mature Flag/Pennant may carry over after the handoff, but no new Flag/Pennant discovery is allowed.

3. **Latched recovery below 38.2% could put broad pattern scanners back to sleep.**
   - Triangle/Wedge, Head & Shoulders, and Channel now accept the explicit broad-layer permission independently of the instantaneous retracement percentage.
   - Their state still records the true current retracement percentage.

4. **Coordinator priority favored an early reversal candidate over a fully valid trigger.**
   - `VALID_TRIGGER` now outranks `EARLY_REVERSAL_CANDIDATE`.
   - An early Multiple Top/Bottom signal can add independent context but cannot force WAIT when another eligible specialist already has a valid trigger.

5. **Structure risk required an explicit Coordinator block.**
   - Persistent H1/Fibonacci structure risk now produces `SLEEPING / M15_BLOCKED_BY_H1_STRUCTURE_RISK`.

### Frozen coordination behavior
- Shallow H1 correction before the >=38.2% latch:
  - Flag/Pennant early access only.
  - Broad specialists cannot make the opportunity package actionable.
- After H1 qualifies >=38.2%:
  - Broad M15 remains active even if current retracement recovers below 38.2%.
  - New Flag/Pennant discovery remains disabled.
  - A Flag/Pennant already mature before the handoff may finish.
- At persistent >=78.6% structure risk:
  - All M15 trade-opportunity coordination is blocked until H1 resets/rolls.
- Coordinator hierarchy:
  - fully valid eligible trigger > early reversal candidate;
  - same-event descriptions are duplicates, not confidence stacking;
  - distinct same-direction events are independent confirmations;
  - opposite actionable evidence is conflict;
  - stale triggers cannot reach Supervisor review.

### Validation results
Full regression suite: **141 / 141 passing**.

New regression coverage includes:
- explicit eligible-agent filtering;
- structure-risk Coordinator sleep;
- valid-trigger priority over early candidate;
- broad-layer latch remaining active below 38.2%;
- new Flag discovery remaining disabled during latched recovery;
- shallow Flag-only phase excluding broad specialists from the Coordinator.

### Next step
Validate each M15 specialist's pattern-specific output contract and then the normalized Opportunity Package on representative M15 replay scenarios. The next validation should focus on stop references, freshness, event identity/deduplication, conflict labeling, and handoff to the Supervisor without changing the frozen H4/H1/Fibonacci rules.
