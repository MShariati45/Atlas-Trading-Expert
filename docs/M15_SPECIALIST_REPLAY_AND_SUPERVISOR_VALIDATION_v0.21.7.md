# Atlas Trading Expert v0.21.7

## M15 specialist replay and Supervisor validation

This checkpoint validates representative replay scenarios for all six M15 specialists against the frozen v0.21.4 H1 -> Fibonacci -> M15 handoff and the v0.21.6 normalized specialist contract.

### Specialist replay results

- M15 Impulse & Correction: CHoCH alone remains non-actionable; meaningful HL/LH plus BOS creates VALID_TRIGGER with buffered structural stop.
- M15 Multiple Top/Bottom: neckline break remains EARLY_REVERSAL_CANDIDATE and waits for independent structure confirmation when alone.
- M15 Flag/Pennant: valid flag breakout normalizes to a Supervisor-ready trigger with consolidation-based stop.
- M15 Triangle/Wedge: geometric boundary break plus required structural break normalizes to Supervisor-ready trigger.
- M15 Head & Shoulders: valid neckline break/retest normalizes with structural stop and now expires after its configured freshness window.
- M15 Channel: valid continuation/retest trigger normalizes with structural stop and now expires after its configured freshness window.

### Fixes made

1. Channel VALID_TRIGGER freshness is now bounded by `stale_after_bars`; stale trigger reason is `CHANNEL_TRIGGER_STALE`.
2. Head & Shoulders VALID_TRIGGER freshness is now bounded by `stale_after_bars`; stale trigger reason is `HEAD_SHOULDERS_TRIGGER_STALE`.
3. Retest-confirmed Channel and H&S entries reset freshness age from the actual actionable trigger rather than inheriting the earlier breakout age.
4. Coordinator same-event matching now understands specialist-specific trigger timestamps (`bos_time`, `structural_break_time`, `confirmation_time`, `neckline_break_time`, `breakout_time`). Different timestamps at the same entry price remain independent events; matching timestamps can be deduplicated.
5. Fixed gross 2R and post-cost R:R are now separated. `RiskPolicy.min_net_rr_after_costs` is optional and defaults to `None`. Spread/slippage remain hard gates. Net R:R remains measured and reported. A stricter post-cost minimum can be explicitly enabled without silently changing the fixed-2R strategy.

### Supervisor hard-gate validation

Direct Opportunity Package -> Supervisor tests verify:

- READY + fresh + structural stop + clear safety gates can APPROVE.
- stale trigger -> REJECT.
- missing structural stop -> REJECT.
- Coordinator conflict -> REJECT.
- explicit post-cost R:R floor can reject when configured.

### Regression status

160 / 160 tests passing.

### Frozen upstream logic

No H4, H1, Fibonacci, or pattern-definition strategy rules were changed in this checkpoint. Changes are limited to M15 trigger freshness/event identity and execution-policy handoff behavior.

### Next recommended step

Run representative real M15 candle-history replays (starting EURUSD, then GBPUSD) through the live specialist runtime to measure detection frequency, false/duplicate trigger rates, trigger age, stop distance, gross/net R:R, and Supervisor rejection reasons. After that, freeze the M15 specialist/coordinator/Supervisor contract before broader multi-symbol calibration.
