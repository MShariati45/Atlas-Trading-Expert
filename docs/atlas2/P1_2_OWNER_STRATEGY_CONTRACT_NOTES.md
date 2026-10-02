# Atlas v2 P1-2 — Owner Strategy Contract Closure

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, and dual-runtime validation complete

## Scope

P1-2 converts the owner-supplied entry/stop-loss decision into an immutable, deterministic research contract without adding execution authority.

## Implemented

- Added `atlas2.strategy.owner_entry`.
- Bound the policy to source SHA-256 `45a83b5c9f0dc6240143dfff1ca3e4a0c367c635e4ef2d8e77656cee32ec0e86`.
- Preserved pattern-specific M15 entry and structural stop rules without inventing exact fill prices where the source is shorthand.
- Preserved H4/Fibonacci as context/location only, never an entry trigger.
- Kept H1 context-only/informational.
- Added Track A research StrategyVersion generation for the 2R + BE@1.4R baseline and no-BE ablation.
- Added ATR(14) research buffer variants 0, 0.10 and 0.20 ATR; 0.10 is the starting test only.
- All Track A versions remain `execution = NONE` and `research_only = true`.
- Policy version is embedded in the strategy version label and full plan identity.

## Not invented

Meaningful/valid swing definition, retest-hold definition, rejection-candle qualification, structural-level identification details, exact shorthand fill rules, 2R realism test, and final per-instrument ATR buffer remain explicit unresolved research/owner parameters.

## Review

Initial independent review found H1 incorrectly hard-gated and an incomplete unresolved list. Both were fixed, along with version-label binding and shared-mutable-role cleanup.
Independent re-review result: **PASS**.

## Validation

- Focused owner-strategy + architecture tests, Python 3.14: **10/10 PASS**.
- Focused owner-strategy + architecture tests, Python 3.12: **10/10 PASS**.
- Full Atlas v2 suite, Python 3.14: **192/192 PASS**, plus **236 subtests PASS**.
- Full Atlas v2 suite, Python 3.12: **192/192 PASS**, plus **236 subtests PASS**.
- `python3 -m compileall -q atlas2`: PASS.
- `git diff --check`: PASS.

## Scope preserved

No broker SDK, MT5 connection, order execution, Demo/Live authority, production outcome promotion, UI, paid service, or legacy `atlas/` modification was introduced.
