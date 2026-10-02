# Atlas v2 P1-1 — Read-Only Shadow / Replay Scope

Owner: Ali Shariati
Status: CLOSED — implemented, reviewed, and validated

## Goal

Create the first runnable P1 surface without adding trade authority: a deterministic, read-only Shadow report over sealed P0 evaluation evidence.

## Included

- Read existing `atlas.sqlite3` in SQLite read-only mode.
- Require a known run manifest and consume only manifest-confirmed sealed aggregates.
- Preserve the existing manifest replay digest.
- Report evaluation context, dataset/instrument, candidate count, arm count, strategy key/version, decisions, reason codes, taints, and seal digests.
- Emit deterministic canonical JSON suitable for replay-to-replay comparison.
- C0 is reportable now.

## Explicitly not included

- Owner Track A semantics.
- Production outcome resolution.
- Entry-order assumptions.
- Portfolio sizing/risk governor.
- MT5, broker SDK, network ingestion, order dispatch, Demo, Live, UI, or paid services.
- New persistence tables.

## Owner decision still open

Exact entry-order semantics remain unresolved under the P0 architecture freeze. Until Ali answers that rule, no production outcome resolver may claim non-proxy truth.

## Evolution rule

P1-1 is additive. Owner Track A, the outcome resolver, forward Shadow ingestion, and later Demo integration attach through versioned P1 components without rewriting P0 evidence.
