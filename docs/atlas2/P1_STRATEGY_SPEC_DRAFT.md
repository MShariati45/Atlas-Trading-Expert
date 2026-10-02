# Atlas v2 — Owner Track A Strategy Spec v1 (DRAFT)

Owner: Ali Shariati
Status: DRAFT — owner review/signature required before freeze

This document records only semantics already supported by the owner answers and frozen Atlas design. Open details are not guessed.

## Detection / evaluation order

1. M15 setup first.
2. H4 context / Last Impulse authority.
3. H1 context where the setup requires it.
4. Fib/correction-location measurement.
5. Supervisor combines evidence and records accept/reject/abstain reasons.
6. Entry plan is attached only after the candidate passes the active strategy gates.

## H4

- H4 Last Impulse is owner-authoritative/manual where automation is not yet trustworthy.
- H4 disagreement is a gate result, not a candidate-relation type.
- Minor/major correction classification follows the frozen extension table and remains derived state.

## H1

- H1 is setup-dependent rather than a universal mandatory gate.
- Exact pattern-specific H1 semantics remain an owner question before the Track A freeze.

## Fib / correction location

- Fib measures correction/location; it is not itself an entry signal.
- Owner interpretation: below 38.2% = minor correction; above 38.2% = major correction.
- Exact equality/body-vs-wick measurement semantics remain open and must be resolved before freeze.
- CORRECTION_LOCATION may not silently become an entry gate without an explicit strategy-version change.

## Baseline plan

- target: 2R
- move stop to breakeven at +1.4R
- required ablation: same 2R plan without breakeven

## Session/day

- intended live days: Monday-Thursday
- intended active sessions: London + New York
- Friday and Asia are outside the current owner baseline
- exact clock/session roll rules remain open until the broker/server time question is resolved

## News

- major relevant-event risk filter is intended around approximately one hour
- exact event relevance and timing behavior remain open; P1 must not invent them

## Daily/portfolio scenario

- max 2 new trades/day
- 0.5% risk per trade
- 1% planned new daily risk
- in P1 this is a reported simulation, not broker execution authority

## Active comparison arms

- Track A: Owner strategy
- C0: minimal control
- Track B: optional indicator-assisted challenger, research-only
- original indicator-free and indicator-assisted tracks remain logically separate for comparison

## Open owner decisions before strategy freeze

- Q1 broker/server/chart source and H4 grid/export timestamps
- Q2 correction depth measurement convention and exact 38.2 equality rule
- Q3 day-roll/session windows/carried-trade allocation
- Q4 pattern-specific H1 semantics
- Q5 exact news-filter behavior
- exact entry execution semantics before outcome simulation is promoted from fixture/contract to production

## Freeze rule

After owner review, the final spec SHA-256 is bound into the strategy version. Any later semantic change creates a new strategy version; it does not rewrite prior Shadow evidence.
