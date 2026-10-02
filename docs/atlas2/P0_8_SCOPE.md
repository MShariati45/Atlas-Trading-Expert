# Atlas v2 P0-8 — Conditional Legacy Import

Owner: Ali Shariati
Status: implementation scope

Source of truth: Atlas v2 Lean Implementation Design v2, sections 10.1, 11, and roadmap step 8.

P0/P1 never imports or executes `atlas.*`. Legacy is data only: copied files opened read-only, recorded outputs, and explicit provenance.

## H4 history boundary

The expected source is a copied `h4_impulse_history` SQLite database. It is opened only through a SQLite read-only URI. The original Desktop backup is never modified or extracted in place.

No legacy schema is guessed. Import requires an explicit mapping profile whose table/column names and raw-value mappings are validated against the copied database.

Mapped rows become existing P0-5 label evidence:
- owner rows -> `LEGACY_IMPORT`, labeler `legacy:owner`;
- engine rows -> `ENGINE`, labeler `legacy:engine`;
- anchor time defaults to `UNKNOWN_LEGACY`;
- an exact unique price match inside the task's frozen dataset may propose a bar time as `INFERRED_RECONSTRUCTION`;
- a proposal never proves the owner meant that candle or knew it then;
- legacy-derived evidence is never operational Track-A authority.

## Provenance

A minimal immutable import ledger records:
- source SHA-256 and byte size;
- source basename;
- schema digest;
- canonical mapping profile;
- source-row digest;
- target task/group IDs.

The source hash is checked before and after import. Any source change aborts the import.

## Conditional source rule

If the copied H4 history database or a required recorded report is absent, the result is **NOT VERIFIED**. P0-8 does not fabricate rows or infer a schema from unrelated archives.

## Recorded-report checkpoint

Recorded legacy outputs are hash/checkpoint inputs only. P0-8 does not execute the legacy runtime. A checkpoint may verify a supplied file hash; absent sources are explicitly NOT VERIFIED.

## Upgradeability

P1 may vendor reviewed M15 specialist source under `atlas2/detect/m15_v025/` only after source closure and parity review. That future adapter does not change P0-8 import evidence.

## Scope exclusions

No legacy runtime execution, no `atlas.*` import, no Demo execution changes, no broker SDK, no strategy authority migration, no archive deletion, and no mutation of `Desktop/Atlas Trading`.
