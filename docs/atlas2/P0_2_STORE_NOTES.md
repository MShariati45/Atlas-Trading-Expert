# P0-2 Store Closure

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, review fixes, and integration tests complete

## Implemented

- One local `atlas.sqlite3` with WAL, `synchronous=FULL`, foreign keys ON, `trusted_schema=OFF`, busy timeout, recursive triggers, and STRICT tables.
- Forward-only migrations with filename inventory and pinned SHA-256 hashes.
- Migration code hashes bytes once and executes those exact bytes inside one `BEGIN IMMEDIATE` transaction.
- Bootstrap migration ledger schema includes the same 64-hex SHA constraint as migration 0001.
- Raw content-addressed blob store uses validated metadata, temp write, file fsync, atomic rename, directory fsync, and SHA-256 verification on read.
- Repository validates frozen models before persistence.
- Request-key idempotency has one write path: same actor/action/key + same canonical payload returns the original result/time; changed payload is a logical-key conflict.
- Evidence/run rows are immutable. Duplicate-primary-key `INSERT OR REPLACE` is blocked by schema triggers even on raw SQLite connections without recursive triggers.
- Run attempts allow one terminal row.
- Seal primitives cover the P0-2 relationships only and reject later child insertion.
- Conflict classes distinguish idempotent repeat, identity conflict, logical-key conflict, and seal violation.
- `verify()` checks SQLite integrity, foreign keys, pinned migration history, expected schema/triggers, referenced blob hashes/sizes, and seal digests.
- Backup is self-contained for the DB and referenced raw blobs. Restore validates the manifest, rejects unsafe paths/inventory drift, fsyncs restored files/directories, and verifies the independent restored copy.

## Independent review closure

Claude's P0-2 read-only review returned PASS-WITH-FIXES with six important Store issues:
1. raw-connection `INSERT OR REPLACE` immutability;
2. schema/trigger drift detection;
3. canonical stored JSON;
4. one request-key write path;
5. exact hashed migration bytes + bootstrap hash-length constraint;
6. durable restore fsync.

All six were fixed. Cheap review minors were also addressed where they improved correctness without widening scope: child-digest helper decoupling, unknown seal-kind validation, single model validation in `put`, and directory fsyncs.

No second review round is required by the reviewer after these fixes if the integration suites are green.

## Validation

- `python3 -m unittest discover -s tests/atlas2 -v`: **56 passed**.
- `python3.12 -m unittest discover -s tests/atlas2 -v`: **56 passed**.
- P0-1 tests remain green.
- Legacy `atlas/` unchanged.
- No network, broker SDK, execution path, paid dependency, or external service was introduced.

## Deferred by design

Registry/Holdout is P0-3. Market normalization/HTF and availability propagation are P0-4. Labels, candidate capture, evaluation/replay, legacy import, broker execution, strategy logic, and UI remain out of P0-2.
