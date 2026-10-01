# ADR-007 — Evolutionary Upgradeability and Migration-First Architecture

Owner: Ali Shariati  
Status: ACCEPTED

## Decision

Atlas v2 must evolve by additive, versioned upgrades rather than periodic rewrites. Every stage must leave the system in a state where the next stage can be introduced through a bounded migration, adapter, new versioned contract, or isolated replacement component without taking the whole system apart.

## Required design rules

1. Stable domain boundaries first. Trading semantics, data evidence, research state, execution, and UI remain separate modules with explicit contracts.
2. Additive schema evolution. Existing immutable evidence is never rewritten in place to fit a new feature. New fields/tables/contracts arrive through forward-only migrations.
3. Version all behavior that changes meaning: strategy versions, selector policies, normalizers, data policies, experiment definitions, execution policies, and model/provider versions.
4. Old evidence remains readable. A new implementation may supersede an old component, but historical runs must keep resolving against the versions they originally pinned.
5. Adapters instead of cross-cutting patches. External brokers, AI/model providers, data vendors, and future execution transports enter behind narrow interfaces.
6. No hidden dual logic. During a migration, one source of truth is designated explicitly; compatibility bridges are temporary, named, tested, and removable.
7. Backward-compatible rollout where practical. A new component must be deployable beside the prior stable path, validated, then promoted through an explicit gate.
8. Fail closed at safety boundaries. Migration convenience never bypasses risk, holdout, execution, approval, or provenance controls.
9. No future-SaaS abstractions unless a current private-stage requirement needs them.
10. Every stage closes only after deterministic tests, migration/schema verification, and a reversible deployment/rollback story appropriate to that stage.

## Operational consequence

Normal upgrades should look like:

old stable version -> additive migration/new component -> shadow/compatibility validation -> explicit promotion -> retire old component later

not:

stop system -> rewrite large sections -> copy old logic manually -> hope behavior matches.

## Exceptions

A rewrite is allowed only when the owner explicitly approves it after evidence shows that an existing boundary is fundamentally unsafe or cannot support the required behavior through a bounded migration. The reason and replacement plan must be documented before code changes begin.
