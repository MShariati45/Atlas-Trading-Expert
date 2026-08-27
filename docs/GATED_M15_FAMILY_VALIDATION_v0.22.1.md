# Atlas v0.22.1 — Gated M15 Pattern-Family Validation

## Scope
Validation-only checkpoint on top of v0.22.0. No H4, H1, Fibonacci, M15 pattern-definition, Coordinator, Supervisor, or risk-policy rule was changed.

## Purpose
Close the remaining live-runtime evidence gap for PENNANT, ASCENDING_TRIANGLE, and FALLING_WEDGE using real EURUSD M15 history with H4/H1 alignment and H1 Fibonacci permissions applied before M15 discovery.

## Real gated examples

### Bear Pennant — 2021-06-02 09:30 UTC
- H1 permission: SHORT
- Fibonacci state: ACTIVE_SHALLOW
- Fibonacci retracement: 0.0% at trigger bar
- Specialist: M15_FLAG_PENNANT
- Pattern: BEAR_PENNANT
- Entry reference: 1.21758
- Raw structural stop anchor: 1.21915
- Final buffered stop: 1.219278
- Coordinator: READY_FOR_SUPERVISOR_REVIEW
- Event identity: M15_FLAG_PENNANT|2021-06-02T09:30:00+00:00|1.21758|BEAR_PENNANT
- A later, separate Bear Pennant at 11:00 UTC received a different event identity after the earlier trigger's freshness lifecycle, confirming separate events are not merged.

### Falling Wedge — 2021-05-19 04:00 UTC
- H1 permission: LONG
- Fibonacci state: ACTIVE_LATCHED_RECOVERY
- Fibonacci retracement: ~5.1095%
- Specialist: M15_TRIANGLE_WEDGE
- Pattern: FALLING_WEDGE
- Entry reference: 1.22325
- Raw structural stop anchor: 1.22191
- Final buffered stop: 1.22179
- Coordinator: READY_FOR_SUPERVISOR_REVIEW
- Event identity: M15_TRIANGLE_WEDGE|2021-05-19T04:00:00+00:00|1.22325|FALLING_WEDGE

### Ascending Triangle — 2019-12-31 02:15 UTC
- H1 permission: LONG
- Fibonacci state: ACTIVE_LATCHED_RECOVERY
- Fibonacci retracement: ~20.9184%
- Specialist: M15_TRIANGLE_WEDGE
- Pattern: ASCENDING_TRIANGLE
- Entry reference: 1.12125
- Raw structural stop anchor: 1.11992
- Final buffered stop: 1.11980
- Coordinator: READY_FOR_SUPERVISOR_REVIEW
- Event identity: M15_TRIANGLE_WEDGE|2019-12-31T02:15:00+00:00|1.12125|ASCENDING_TRIANGLE

Additional gated Ascending Triangle examples were observed on 2019-08-12, 2019-07-31, and 2019-01-06/07.

## Contract checks
- All three previously missing families now have real HTF/H1/Fibonacci-gated live-runtime evidence.
- Each actionable event contains a non-null entry reference, raw structural stop anchor, final buffered stop, trigger time, and deterministic event identity.
- Coordinator state is READY_FOR_SUPERVISOR_REVIEW for the representative events.
- Existing freshness regression remains authoritative: fresh Flag/Pennant and Triangle/Wedge triggers cannot be overwritten by rediscovery and age to STALE after the configured freshness window.
- Existing Supervisor hard-gate integration remains authoritative: malformed/stale/conflicting packages are rejected; a clean package with all external safety gates green can be approved.

## Freeze decision
The M15 pattern-family discovery contract is accepted as a freeze candidate at v0.22.1 for live discovery semantics and handoff structure. This does not mean profitability or production readiness is proven. Pattern expectancy, symbol-specific frequency, execution costs, and Supervisor safety performance still require broader historical/demo validation.
