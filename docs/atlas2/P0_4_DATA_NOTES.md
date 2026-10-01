# Atlas v2 P0-4 — Canonical Data / Availability / Dataset / HTF / Views

Owner: Ali Shariati  
Status: **CLOSED — implementation, integration review, and dual-runtime tests complete**

## Closed behavior

- Raw source bytes remain content-addressed blobs; SourceObservation remains separate provenance.
- Canonical Bar, Quote, CalendarSchedule, and CalendarValue facts are source-independent semantic facts.
- Bar/Quote/Calendar fact IDs are recomputed from semantic content during validation.
- Calendar numeric values are stored as canonical non-exponent decimal text.
- FactLink carries source observation, locator, normalizer version, availability basis/time, and quality flags.
- Quote normalization preserves source sequence. Missing sequence stays NULL and sets MULTIPLICITY_UNKNOWABLE.
- A bar FactLink cannot claim availability before the bar close.
- Historical calendar availability is never manufactured. UNKNOWN stays invisible to PIT and appears only in NON_PIT sensitivity reads with NON_PIT_MACRO taint.
- FORWARD MarketView knowledge time is max(link availability, actual Atlas acquisition time).
- Several observations may point to one fact. A fact becomes usable from its earliest eligible knowledge time; revisions on the same natural key take effect only from their own availability.
- Frozen DatasetVersion identity binds membership digest, coverage, causal policy, HTF policy, precedence policy, clock profile, instrument specs, and tzdata version. display_name and built_at_us are metadata.
- Dataset membership is atomically sealed through the shared Store seal mechanism. No membership can be appended after freeze.
- MarketView and OutcomeView use separate holdout routes. Protected instrument reads record P0-3 Exposure before returning data.
- Calendar reads conservatively guard every overlapping protected instrument in the requested interval.
- H1/H4/D1 synthetic derivation uses visible M15 constituents only. Source-supplied HTF bars are never substituted.
- Late constituents stay invisible until available; missing constituents after target close produce INCOMPLETE_MISSING_INPUT; forming bars are PARTIAL_FORMING.
- P0-4 synthetic HTF grid is UTC-aligned and explicitly versioned. Real broker/server H4 alignment remains Owner Q1 and is not guessed.

## Store/schema

- Added pinned forward migration 0005_data.sql.
- Existing generic Store now persists data facts/links/datasets/memberships through the same validated SQL boundary.
- Added atomic put_many_and_seal for frozen aggregate creation.
- Pinned migrations may use DROP only because the exact migration bytes are hash-pinned; 0005 replaces the earlier generic seal-parent trigger to add data_datasets.
- New data tables are STRICT and append-only; UPDATE/DELETE/INSERT OR REPLACE attempts are rejected.
- Schema verification replays all pinned migrations in-memory, including the trigger replacement.

## Validation

- Python 3.14: **87/87 PASS**
- Python 3.12: **87/87 PASS**
- compileall: PASS
- git diff --check: PASS
- Existing P0-1/P0-2/P0-3 tests remain green.
- P0-4 coverage includes overlapping observations, revision timing, FORWARD acquisition time, UNKNOWN calendar PIT exclusion, calendar decimal canonicalization, quote multiplicity flags, late/missing/partial HTF constituents, source-HTF rejection, dataset identity, dataset sealing, holdout-before-return for market/outcome/calendar reads, early-bar availability rejection, identity binding, immutability, and schema verification.

## Deferred by frozen design

- Real broker/server clock profile and exact H4 grid: Owner Q1.
- Real M15/M1/bid-ask/calendar export normalization: Owner Q6 / actual supplied exports.
- Broker-specific DST/week-open verification starts when the real clock/export is supplied.
- Labels, candidate detection, strategy logic, outcomes, broker connection, execution, and UI are later stages.

## Independent-agent audit note

Read-only Codex/Astra and Claude review commands were launched against the isolated P0-4 worktree, but both local provider sessions were at their usage/session limits. Per the owner instruction not to stall implementation on tooling quotas, P0-4 was closed after direct integration review and both runtime suites passed. A later read-only external audit may inspect this immutable checkpoint without rewriting its history.
