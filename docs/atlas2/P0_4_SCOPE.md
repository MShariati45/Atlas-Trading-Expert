# Atlas v2 P0-4 — Canonical Data, Availability, Dataset, HTF & Views

Owner: Ali Shariati
Status: implementation scope

P0-4 implements the smallest causal data spine required before labels/candidates. The governing rule is: a decision at instant d may use an input only when that input is operationally available at or before d.

## Contracts

- RawBlob -> SourceObservation -> CanonicalFact -> FactLink -> DatasetMembership.
- Canonical facts are source-independent semantic facts. Several observations may link to one fact. Conflicting/revised values are distinct facts sharing a natural key.
- P0-4 fact kinds: Bar, Quote, CalendarSchedule, CalendarValue.
- Availability basis: SOURCE_STAMPED, BAR_CLOSE_RULE, OBSERVED_BY_ATLAS, DERIVED, UNKNOWN.
- UNKNOWN calendar history is invisible to PIT reads. It may be exposed only through NON_PIT sensitivity reads and must carry NON_PIT_MACRO taint.
- No scheduled-minus-lead, ingest-order vintage, or invented historical availability.

## Normalization

- Broker OHLC may use BAR_CLOSE_RULE = close + declared nonnegative publication lag.
- Quotes retain source sequence when supplied. Missing sequence remains NULL; Atlas never fabricates one.
- Historical calendar snapshots without first-seen/publication evidence remain UNKNOWN.
- Forward Atlas-observed calendar records use the actual Atlas acquisition time.
- Price conversion uses pinned instrument digits and integer prices only. No float evidence.

## Datasets

- DatasetVersion freezes an explicit set of fact-link memberships.
- Dataset identity binds membership digest, coverage, causal policy, HTF policy, precedence policy, clock profile, instrument specs, and tzdata version.
- display_name and built_at_us are metadata and do not alter dataset identity.
- Natural-key precedence at as-of t selects the eligible membership with the greatest available_at <= t; ties break by fact_id.
- Frozen datasets are append-only and never mutated.

## HTF

- P0-4 derives H1/H4/D1 from visible M15 facts under an explicit versioned grid policy.
- Source-supplied H4/H1/D1 is never substituted when deriving from canonical M15 constituents.
- Derived availability is max(target close time, availability of all constituents actually used).
- A late constituent remains invisible until its availability.
- Missing expected constituents after target close produce INCOMPLETE_MISSING_INPUT.
- Before target close, the bar is PARTIAL_FORMING.
- Synthetic P0-4 tests use UTC-aligned M15/H1/H4/D1. Real broker/H4 alignment remains Owner Q1 and is not guessed.

## Views / Holdout

- MarketView exposes only facts eligible at as_of under PIT/NON_PIT rules.
- OutcomeView is a separate capability; P0-4 does not pass it into detector/evaluation code.
- Historical MarketView and OutcomeView reads first check overlapping holdout segments.
- Protected reads require a valid holdout grant and record Exposure through the P0-3 holdout guard before returning data.
- Dataset IDs are not part of holdout identity/status.

## Acceptance focus

Synthetic tests must demonstrate:
- overlapping observations of one fact;
- revisions appearing only from their availability;
- UNKNOWN calendar exclusion from PIT and NON_PIT taint;
- late M15 constituent excluded from H4 until available;
- missing constituent => INCOMPLETE;
- source H4 ignored by M15 derivation;
- deterministic dataset identity regardless of membership order;
- holdout protection before view return;
- schema immutability and pinned migration verification;
- existing 69 P0-1/P0-2/P0-3 tests stay green.

## Scope exclusions

No label store, label selection, candidate detection, strategy gates, outcome simulation, live broker feed, execution, UI, paid service, external API, or real broker-grid assumption.
