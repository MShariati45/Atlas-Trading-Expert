# Atlas v2 P0-3 — Registry & Holdout Scope

Owner: Ali Shariati
Status: implementation scope

This stage implements the smallest research-registry and holdout foundation required by the frozen Atlas v2 design. It must not introduce market-data normalization, labels, candidates, strategy logic, outcome simulation, broker/execution code, or UI.

## Experiment registry

- Preregistration payloads are canonical, content-addressed records. Identity excludes self IDs/digests.
- Experiment identity binds preregistration digest, registered_by, and request key.
- Amendments are append-only and bind experiment, sequence, parent effective digest, and new payload digest.
- Trials are append-only identities under an experiment using a monotonic `trial_index` plus canonical parameter point; repeating the same parameter point is a distinct trial when the request is distinct.
- Trial events are append-only with the frozen event vocabulary: PLANNED, STARTED, FAILED, ABANDONED, COMPLETED, INSPECTED, SELECTED, REPLICATED.
- Trial results bind the effective preregistration digest used by the run. PRIMARY is unique per trial; REPLICATION may repeat with distinct attempts.
- A decision is append-only and unique per experiment.
- The effective preregistration becomes sealed at the first protected holdout exposure under the experiment or the first STARTED trial event, whichever occurs first. Amendments after that point remain recorded but make confirmatory eligibility false rather than rewriting history.
- Total trial count is audit evidence only; later statistical methods define their own search sets.

## Holdout

- Holdout segments are independent of dataset version and defined by instrument plus half-open interval `[start_us, end_us)` with purpose FINAL_OOS.
- Exposure is append-only and records segment, actor, purpose, route, covered interval, grant reference, batch session ID, and served_at timestamp.
- Supported P0-3 route vocabulary: MARKET_VIEW, OUTCOME_VIEW, LABEL_TASK, EXPORT. Actual data serving arrives later; P0-3 exposes the guard primitive only.
- A grant belongs to a confirmatory or promotion-review experiment and pins the effective preregistration digest.
- Per the architecture-freeze addendum, one grant maps to one deterministic batch session: `batch_session_id = domain-hash(grant_id, effective_prereg_digest)`. Retries under the same grant reuse the same batch session. A different grant or effective preregistration creates a different session.
- The first preregistered batch session may make repeated reads under that same session. A different/adaptive session over the protected segment marks the segment inspected/exposed for later promotion decisions.
- Exposure is recorded before the guard returns permission to serve data.
- Re-versioning/re-exporting a dataset cannot reset holdout status because holdout identity is instrument/time coverage, not dataset ID.
- Outcome windows that overlap a protected segment count as exposure of that segment.
- Direct raw SQLite/file access is not observable; the design states this limitation rather than pretending prevention.

## Implementation constraints

- One SQLite file; forward-only pinned migration.
- All registry/holdout evidence is immutable/append-only.
- Reuse the P0-2 Store/request-key/verification patterns; do not duplicate them.
- No hidden mutable current-state columns. Derived status is queried from append-only events/exposures.
- No paid dependencies or services.
- No Git/GitHub writes by implementation agents; integration room owns stage commit/push after tests/review.
