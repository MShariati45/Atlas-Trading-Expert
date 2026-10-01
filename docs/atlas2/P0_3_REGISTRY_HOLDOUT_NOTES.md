# Atlas v2 P0-3 Registry & Holdout

Owner: Ali Shariati
Status: CLOSED — implementation, integration review, and dual-runtime tests complete

## Implemented

- Canonical content-addressed preregistrations with self-reference fields rejected.
- Experiment identity binds preregistration digest, registered_by, and request key.
- Request-keyed experiment, amendment, trial, trial-event, result, decision, grant, and exposure writes reuse the shared Store idempotency transaction.
- Amendments are append-only, sequential, and parent-effective-digest checked.
- Trial parameter points are canonical; identity includes experiment + monotonic trial_index + parameter point, so repeated parameter points remain distinct trials while retries remain idempotent.
- Trial events use only PLANNED, STARTED, FAILED, ABANDONED, COMPLETED, INSPECTED, SELECTED, REPLICATED.
- STARTED pins a trial's effective preregistration; later events/results remain pinned to that started trial even if the experiment is amended later.
- PRIMARY result is unique per trial; REPLICATION is distinct by run attempt.
- One immutable decision per experiment.
- Experiment seal state is derived from the first STARTED trial event or first protected holdout exposure, using one cross-evidence order allocated by the supported registry path.
- Post-seal amendments remain recorded and make derived confirmatory eligibility false.
- Holdout segments are instrument + half-open [start,end), FINAL_OOS only, with no dataset identity.
- Holdout grants are restricted to CONFIRMATORY or PROMOTION_REVIEW experiments, pin an effective preregistration, and retain their request key so grant identity is fully reconstructible.
- batch_session_id is deterministic from grant_id + effective preregistration digest.
- Holdout guard clips the protected interval overlap, writes Exposure and request receipt in one SQLite transaction, then returns permission.
- Repeated reads under one grant reuse one batch session. A second grant/session over the same protected segment makes derived status INSPECTED and confirmatory eligibility false.
- An unused grant becomes stale after preregistration amendment. A batch session that already began may finish under its original pinned preregistration; the post-seal amendment still disqualifies confirmatory eligibility.
- Dataset versions never enter holdout identity or status.
- Research evidence tables are STRICT, immutable, append-only, and covered by pinned schema verification.

## Scope boundaries preserved

No market normalization, HTF derivation, labels, candidate capture, strategy logic, outcome simulation, broker SDK, execution transport, UI, paid dependency, or external service was introduced.

## Validation

- `python3 -m unittest discover -s tests/atlas2 -v`: **69 passed**.
- `python3.12 -m unittest discover -s tests/atlas2 -v`: **69 passed**.
- All 56 P0-1/P0-2 tests remain green; 13 focused P0-3 tests are green.
- New P0-3 tests cover prereg hash stability, request retry, amendment lineage, STARTED/exposure seal points, post-seal amendment disqualification, event vocabulary, PRIMARY uniqueness, decision uniqueness, grant restriction, deterministic batch sessions, exposure/request transaction rollback, same-session repeat, adaptive second session, overlap clipping, stale-grant behavior, dataset-version independence, immutability, and schema verification.

## Review closure

The integration room performed a contract/code review after the isolated implementation and fixed two additional P0-3 consistency issues before closure: trial identity now restores the frozen design's `trial_index`, and holdout grant identity stores its request key so the full identity preimage is reconstructible.

Claude and Codex CLI independent-review attempts were blocked by their local provider/session usage limits, not by a code or architecture blocker. Per the owner instruction not to stop progress on tooling quotas, this did not hold the stage open after the integration review and both runtime suites were green. A later external re-read may audit the closed checkpoint without changing its evidence history.

