# Atlas v2 P0-9 — Hardening and P0 Closure

Owner: Ali Shariati
Status: implementation scope

Source of truth: Atlas v2 Lean Implementation Design v2, sections 5.20–5.24, 8.4–8.5, 13 P0 step 9, and 16 P0 Definition of Done.

P0-9 closes the offline evidence/replay foundation. It does not add trading semantics.

## Audit and request evidence

- Fresh request-key writes append one hash-chained AuditEvent in the same transaction.
- Retries return the original request result and append no new audit event.
- Audit rows pin recovery epoch, event type, actor, time, subject/result ref, canonical request evidence, previous hash, and record hash.
- Verification recomputes the complete chain from genesis.
- Audit is tamper-evident relative to an external checkpoint; it is not claimed tamper-proof.

## Backup

A published P0 backup is self-contained and includes:
- online SQLite snapshot + hash;
- all referenced raw blobs + hashes;
- audit head (seq/hash);
- current recovery epoch;
- declared config/policy files;
- code-ref metadata;
- optional lockfile hash/copy;
- tzdata version.

Publication is temp/atomic at the directory level: a failure before the atomic rename removes the temporary package. After the verified package is published and its parent directory is fsynced, a separate external-checkpoint failure is reported but the valid backup package is retained.

## External checkpoint

At backup, the audit head may be appended to a small external checkpoint file outside the store. Records are lineage-linked and bind backup-manifest digest plus audit seq/hash. A restored KNOWN_RANGE fork must begin a new checkpoint log before future backup checkpoints are appended. No network or paid service is required.

## Restore

Restore:
1. verifies the backup set before trusting it;
2. copies only manifest-listed safe relative paths into a clean directory;
3. verifies the restored store using only the backup set;
4. compares the backup audit head with the latest supplied external checkpoint;
5. appends a new RecoveryEpoch row;
6. appends restore audit evidence under the new epoch;
7. checkpoints/fsyncs the restored database and files.

missing_tail:
- NONE — external checkpoint exactly matches the restored backup head;
- KNOWN_RANGE — a verified external-checkpoint lineage extends beyond the restored head;
- UNKNOWN — checkpoint is absent/behind/mismatched.

## Verification

Store verification is read-only and checks:
- SQLite integrity + foreign keys + pinned migration history;
- raw blob hash/size without creating directories;
- seals;
- audit hash chain.

## Hardware baseline

P0 records the current development host baseline (OS, arch, Python, SQLite, logical CPU, memory when available, disk free). These are observations only; **no numeric pass/fail gate** is introduced.

## P0 Definition-of-Done manifest

The hardening suite maps the frozen P0 DoD to deterministic tests already built across P0-1…P0-8 plus P0-9 recovery tests. The six-week synthetic fixture contract is `fx_eurusd_6w`, spanning the March 2026 US/EU DST transitions. Real-export validation remains optional until owner Q1/Q6 inputs are supplied.

## Upgradeability

P1 Shadow consumes the closed P0 contracts. Recovery metadata, backup format, audit events, and hardware baseline are additive infrastructure and cannot become strategy authority.

## Scope exclusions

No MT5 import, no broker connection, no order API, no P1 owner strategy, no production outcome resolver, no portfolio sizing, no UI, no paid service, no Live capability.
