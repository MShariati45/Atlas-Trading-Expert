# Atlas v2 P1-1 — Shadow / Replay Closure

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, and dual-runtime validation complete

## Implemented

- Added `atlas2.shadow` as a P1 read-only reporting boundary.
- Added deterministic `build_shadow_report(db_path, manifest_id)`.
- Added canonical JSON rendering and a minimal module command surface.
- SQLite opens with `mode=ro`, `PRAGMA query_only=ON`, and one pinned read transaction.
- Reports consume only manifest-confirmed, sealed evaluation contexts and their manifest-confirmed capture units.
- No new table or schema migration was added.
- Replay identity reuses the canonical `replay_digest_for_store` implementation.
- Compared report payloads contain semantic candidate/arm fields, not attempt-derived candidate/arm IDs.
- C0 is explicitly identified as `C0_MINIMAL_CONTROL/v1`.
- Report authority is explicitly `NO_ORDER`.
- Owner Track A is explicitly `NOT_IMPLEMENTED`.
- Entry semantics remain explicitly `OWNER_DECISION_PENDING`.

## Independent review

Initial read-only review found four concrete issues: attempt-derived IDs in comparable output, no pinned SQLite snapshot, capture confirmation not required, and duplicated replay-digest SQL.
All four were fixed.
Independent re-review result: **PASS** with no concrete blocker.

## Validation

- Focused shadow/evaluation + architecture tests, Python 3.14: **34/34 PASS**.
- Focused shadow/evaluation + architecture tests, Python 3.12: **34/34 PASS**.
- Full Atlas v2 suite, Python 3.14: **186/186 PASS**, plus **236 subtests PASS**.
- Full Atlas v2 suite, Python 3.12: **186/186 PASS**, plus **236 subtests PASS**.
- `python3 -m compileall -q atlas2`: PASS.
- `git diff --check`: PASS.

## Scope preserved

No Owner Track A trading semantics, production outcome resolver, portfolio sizing, MT5/broker SDK, order authority, Demo/Live transport, network ingestion, UI, paid service, or legacy `atlas/` modification was introduced.

## Next P1 dependency

The exact owner entry-order rule is still required before the production outcome resolver can be promoted beyond `PROXY_OUTCOME`.
