# Atlas v2 P0 Architecture Freeze Addendum

Owner: Ali Shariati
Date: 2026-10-01
Status: Frozen for P0 implementation

This addendum narrows four points in `Atlas v2 Lean Implementation Design v2.pdf` before schema coding. It does not redesign the architecture.

## 1. Holdout batch-session identity

For P0, one holdout grant maps to exactly one deterministic batch session.
`batch_session_id = SHA256(grant_id + effective_prereg_digest)`.
Retries and reruns under the same grant reuse that session ID.
A different grant or changed effective preregistration creates a different session.
This removes ambiguity between legitimate reruns and adaptive second inspections.

## 2. Entry semantics are not frozen yet

P0 does not assume market, limit, stop, or touch-entry semantics.
The outcome resolver remains P1 and cannot be promoted from proxy status until the owner answers the exact entry-order rule.
Any interim simulator assumption must be named, versioned, and tainted `PROXY_OUTCOME`.

## 3. Legacy Demo boundary

P2 should not patch certified legacy execution code in place merely to fit atlas2.
Preferred order: adapter/bridge first; if impossible, a separately versioned fork with explicit file-level diff and tests.
`DemoOnlyMT5Transport` remains byte-identical unless an owner-approved exception is recorded.

## 4. Live enable requires two independent conditions

Limited Live requires both:
1. a valid `OwnerLiveApproval` record matching build, strategy, config, accounts and caps; and
2. a host-local enable token/file matching the approval ID and build hash.

Either missing or mismatched condition means Live is disabled.
The host-local token is never stored in source control or backups and is removed on revocation.

## Implementation rule

P0 coding may proceed now. These four points are binding on subsequent ADRs and tests.
