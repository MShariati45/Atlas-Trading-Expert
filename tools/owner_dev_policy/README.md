# Owner Development Policy (`owner-dev-policy.v1`)

The Owner's project-neutral development operating policy, extracted from the Sigma WorkOffice workflow and
instantiated **independently** inside each project's own development environment:

| Identity | What it is | Relationship to this package |
|---|---|---|
| Personal Command Center | The Owner's private control/monitoring plane | **Consumer only.** Reads each project's monitoring projection and event export; sends abstract control requests. No product runtime executes there. |
| Atlas Trading Expert | Independent product (own runtime, UI, users, data, deployment) | Instantiates this policy via `tools/atlas_dev_workflow/project.py` |
| Alpha Lead Engine | Independent product | May instantiate its own copy/adapter; never shares state with Atlas |
| Sigma WorkOffice | Independent product | Origin of the workflow; own adapter, own state |

No runtime state, product database, auth domain, deployment or UI is shared between these identities.

## Dependency rule

`tools/owner_dev_policy` is stdlib-only and imports nothing from any project or from the Command Center.
Projects depend on it; it never depends on them (enforced by `IdentityBoundaryTests`). Project vocabulary
(e.g. trading terms) never appears here. A project adapter supplies identity, vocabulary, domain gates and
its own Definition-of-Done checks; it may only **add** obligations.

## Modules (one responsibility each)

| Module | Responsibility |
|---|---|
| `schema.py` | Shared errors (`OwnerPolicyError`, `SchemaError`), canonical JSON, digests, strict validators |
| `redaction.py` | Secret redaction and explicit (never silent) truncation of excerpts |
| `classification.py` | Priority model, queue ordering, finding classes and dispositions |
| `providers.py` | Executor catalog defaults, qualification, failover chains, reviewer independence, exhaustion detection |
| `checkpoint.py` | Checkpoint contract and interval rule |
| `compute.py` | Effort tiers, optional usage metrics, budgets, context-truncation report |
| `events.py` | `DevelopmentEvent` contract and idempotent JSONL export |
| `monitoring.py` | Monitoring projection and abstract control-request contracts |
| `glossary.py` | Owner vocabulary; project terms compose but may not shadow it |
| `done.py` | Owner Definition of Done composed with the project DoD |
| `policy.py` | `OwnerDevelopmentPolicy` settings and owned-path lane exclusivity |

## Policy (normative)

1. **Durable coordination.** Git, task records, the project journal, checkpoints, PRs and CI are the shared
   memory; chat is not. A durable task ID, branch, worktree, base SHA and owned paths exist before any edit.
   One task lane per concurrent task; owned paths are exclusive among lanes that can still progress
   (`owned_path_conflicts`). No direct work on protected branches. Checkpoints are written at least every
   `checkpoint_interval_s` (≤ 30 min) of active work and before risky commands, context switches, provider
   exhaustion, handoffs, stops, blocks and waits. Each checkpoint carries exact HEAD, state, owned paths, diff
   summary, commands/results, blockers, risks and exactly one executable next action. Durable state is
   resumed, never re-brainstormed.
2. **Peer coders and provider failover.** Claude Code and Codex are peer coding executors; neither is a
   permanent superior. Each role has an ordered chain in **config** (`role_chains`), not code. Usage, auth or
   rate-limit exhaustion is not retried on the same executor: a checkpoint and a recorded handoff precede the
   successor, which receives the identical handoff and needs no chat history. Gemini is qualified for research
   only unless a project adapter explicitly qualifies it. Executor specs cannot carry permission/authority
   fields: provider identity never implies operational permission. Review must be independent of **every**
   executor that implemented the change, including failover successors.
3. **Research separation.** Research output is untrusted evidence until independently reviewed; the research
   lane has no code-mutation or promotion authority. Popularity or opinion is never self-validating.
4. **Qualification and review.** Offline, credential-free, deterministic checks by default; focused tests,
   regression tests for new behaviour, broader gates and boundary checks; independent review. Review text is
   untrusted: each finding is verified against current code and either fixed or recorded with a disposition
   and reason (`Finding`, `DISPOSITIONS`). Integration decisions rest on executable evidence.
5. **Clean ("OCD-style") engineering.** Obsessive zero-ambiguity quality control, not extra layers.
   Findings are classified `MUST_FIX_BEFORE_IMPLEMENTATION` (blocks development DONE),
   `MUST_FIX_BEFORE_PRODUCTION` (blocks any production boundary), `ACCEPTABLE_TECHNICAL_DEBT`,
   `DEFERRED_SCALE_CONCERN`. The zero-ambiguity pass checklist: unclear words, contradictory docs, duplicate
   or stale concepts, unexplained exceptions, inconsistent filenames, missing cross-references, vague
   ownership, unowned invariants, undocumented dependencies, unresolved TODO language, superseded docs, and
   instructions conflicting with the current freeze.
6. **Anti-spaghetti / blast radius.** Explicit dependency direction, bounded modules, no duplicated
   validation/digest/policy logic, shared helpers only for truly shared responsibility, smallest valid change,
   no speculative compatibility shims, architecture deviations through the project's ADR mechanism,
   destructive changes only with a recorded reason and approval.
7. **Priority.** `CRITICAL_BLOCKER > MUST_FIX_BEFORE_IMPLEMENTATION > MUST_FIX_BEFORE_PRODUCTION > HIGH >
   NORMAL > LOW > ACCEPTABLE_TECHNICAL_DEBT > DEFERRED_SCALE_CONCERN`. Priority orders the queue only; it
   never bypasses a safety, approval, qualification or review gate.
8. **Token/context/compute.** Smallest sufficient task packet; canonical reading order (project reference
   registry), no full-repo dumps; durable summaries instead of resent histories; static project context
   separate from per-task delta; deterministic tools before inference. Effort (`routine|standard|deep`) is
   chosen from task complexity and may be overridden by the Owner without expanding permissions. Usage is
   recorded only when a provider reports it, numeric and bounded; unreported usage is shown as unknown, not
   zero. Optional per-task budgets stop work **before** the next agent call. Context truncation is recorded
   (`context_report`) and propagated; truncated agent output is never accepted. Failure of a first output is
   handled by policy/fallback, never by silently escalating to a stronger paid model.
9. **Graph/evidence logging.** Every meaningful event is exported as an append-only, idempotent, redacted
   `DevelopmentEvent` whose `event_id` derives from `(project_id, source_ref)`. The project journal is the
   source of truth; Graphify and the Command Center are projections.
10. **Vocabulary.** `glossary.OWNER_GLOSSARY`; projects add their own terms and cannot redefine owner terms.
11. **Definition of Done.** `done.evaluate_done` requires every owner requirement (`OWNER_DOD`) and at least one
    explicit project check; missing evidence is failure, and a project cannot shadow an owner requirement.
    Architecture-significant work additionally requires a passed maintainability/zero-ambiguity audit.

## Command Center contract

* **Read:** `monitoring-projection.v1` — project identity, run ID, state, policy class, priority, responsible
  role/executor, attempt/fix cycle, branch/worktree/base/head, qualification, review, blockers, approvals
  needed, usage/budget, context truncation, last checkpoint, evidence refs, one next action, health/staleness,
  terminal result and event linkage IDs.
* **Events:** `event.v1` JSONL export.
* **Control:** `control-request.v1` with actions `pause|resume|cancel|approve|reject|recover`. The request has
  no field able to carry authority or activation. The owning project validates it, checks `requested_by`
  against **its own** authority table, journals the decision and enforces it. Displaying a control grants
  nothing.
