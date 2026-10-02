# Atlas v2 P0-8 — Conditional Legacy Import Closure

Owner: Ali Shariati  
Status: CLOSED — implementation, CodeRabbit review, and dual-runtime validation complete

## Implemented

- Legacy code is never imported or executed. P0-8 treats legacy only as copied/read-only data.
- A copied H4 impulse-history SQLite source is opened through SQLite `mode=ro` with `query_only=ON`.
- Source SHA-256 is checked before/after inspection, scan, and import.
- Import requires an explicit, canonical mapping profile; table/column names and raw actor/trend values are never guessed.
- Mapping pins the legacy price conversion policy and the market price side used for optional bar matching.
- `SCALED_INT` and versioned `SQLITE_REAL_DECIMAL_V1` price policies are deterministic and tested.
- Owner rows become `LEGACY_IMPORT` / `legacy:owner`; engine rows become `ENGINE` / `legacy:engine`.
- Imported evidence is non-operational and legacy-derived engine rows are explicitly tainted.
- Anchors default to `UNKNOWN_LEGACY`.
- Exact unique price matches may propose `INFERRED_RECONSTRUCTION` bar times; ambiguity leaves the time unknown.
- Immutable source/row provenance records source hash, schema digest, mapping profile, source-row digest, task ID, and resulting label group.
- Retry is idempotent. A changed task mapping fails with `IDENTITY_CONFLICT` before creating an orphan label group.
- Required legacy text values fail closed on NULL/non-TEXT values.
- Missing/unidentified real legacy sources are reported `NOT VERIFIED`; no fake parity/import claim is created.

## Real-source checkpoint

The protected `Desktop/Atlas Trading` backup was inspected read-only. The expected copied `h4_impulse_history` database was not found, so **no real H4 history rows were imported**.

The two observed H4 archive hashes were rechecked after P0-8 work and remained unchanged:

- `Atlas_v0.24.13_H4_First_Impulse_Reversal_Origin.zip` — `30ec7b06f536d3527bf8e02aab238c2aae6917b5947e327aeaf8b5d520cc5452`
- `Atlas_v0.24.10_H4_Active_Impulse_Lifecycle.zip` — `55a1971e98b982ccc121b160809487dd8d8eb5919a3fedbfb863a8378807cd8e`

No protected archive was extracted, modified, or deleted.

## CodeRabbit review

The initial review found two minor issues:
- required legacy text values were being string-coerced instead of type-checked;
- unique anchor matching did not explicitly pin the dataset bar price side.

A second review found two further minor hardening points:
- require TEXT exactly in the helper;
- tighten the task-remap regression to assert `IDENTITY_CONFLICT`.

All were fixed. Final CodeRabbit review: **0 findings**.

## Validation

- Python 3.14: **160/160 tests PASS**.
- Python 3.12: **160/160 tests PASS**.
- Focused P0-8 legacy-import tests: **11/11 PASS**.
- `python3 -m compileall -q atlas2`: PASS.
- `git diff --check`: PASS.
- All P0-1 through P0-7 tests remain green.

## Upgradeability

If the actual copied H4 database is supplied later, the importer only needs a reviewed mapping profile; the source/import evidence contract does not change. P1 specialist vendoring/parity is separate and cannot rewrite these imported records.

## Scope preserved

No legacy runtime execution, no `atlas.*` import, no broker SDK, no Demo execution change, no strategy authority migration, no archive mutation, no paid service.
