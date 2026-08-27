# Atlas v0.21.6 - M15 Specialist Output Contract

## Scope
H4, H1, Fibonacci, and pattern-specific detection rules remain unchanged from v0.21.5. This checkpoint hardens the normalized M15 Opportunity Package passed to the Supervisor.

## Valid actionable contract
An actionable M15 report must provide an entry reference, raw structural stop anchor, and final buffered stop. Reports missing any mandatory execution reference are blocked from Supervisor readiness and exposed as contract errors.

## Normalized primary trigger
The Coordinator now emits agent, status, pattern type, direction, entry reference, raw stop anchor, applied buffer, final stop, trigger time, stable event identity, freshness, and reason code.

## Event identity and deduplication
Explicit specialist event IDs remain authoritative. When absent, the normalized primary trigger receives a deterministic identity from specialist + trigger time + entry reference. Cross-specialist duplicate classification still uses explicit shared event ID first, then matching trigger time, then exact entry reference fallback.

## Freshness
Actionable triggers retain existing specialist staleness behavior. The normalized package exposes freshness explicitly for Supervisor audit.

## Result
Full regression suite: 143/143 passing.
