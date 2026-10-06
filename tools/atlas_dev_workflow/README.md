# Atlas Development Workflow Runtime — Operator Runbook

Atlas Trading Expert's own development orchestration runtime (`RUNTIME_VERSION 1.0.0`). It runs five roles
(supervisor, planner, implementer, QA, independent reviewer) over durable task lanes. It is **development
tooling**: it is not part of the `atlas2` artifact, never imports or is imported by `atlas2`, never connects a
broker, sends orders, activates Demo/Live, promotes a strategy or handles credentials.

It instantiates the project-neutral Owner Development Policy (`tools/owner_dev_policy/README.md`) and adds
the Atlas overlay (`policy.py`). Atlas gates can only add obligations to the owner policy, never remove them.

## Layout and dependency direction

```
tools/owner_dev_policy   (project-neutral, stdlib-only)  <-- depends on nothing
        ^
tools/atlas_dev_workflow (Atlas adapter + runtime)        <-- never imported by atlas2/
```

| Module | Responsibility |
|---|---|
| `contracts.py` | Versioned TaskContract, Handoff and agent packet contracts |
| `states.py` | Durable states and the legal-transition table |
| `store.py` | SQLite state: tasks, hash-chained append-only journal, agent runs, approvals, mutation ledger |
| `policy.py` | Atlas overlay: A/B/C classification, experiment/holdout/taint gates, execution boundary, approvals |
| `project.py` | Atlas adapter for the owner policy: project ID, Atlas glossary, effort, responsible role, next action, control authority |
| `supervisor.py` | The only writer of task state: step handlers, failover, owner DoD, operator commands, control enforcement |
| `projections.py` | Read-side views from durable state: checkpoints, monitoring projection, event export |
| `executors.py` | Executor protocol, `FakeExecutor`, `CliExecutor`, failover chain building |
| `gitops.py` | Safe worktree manager and idempotent merge gateway (manual by default) |
| `references.py` | Deterministic lexical reference registry (canonical reading order source) |
| `roles.py` | Role profiles: responsibilities, prohibitions, mutation authority |
| `simulation.py` | Synthetic agents for dry runs and qualification (no model, broker or network) |
| `cli.py` | Operator CLI (JSON output) |

## State

All mutable state lives in the state directory, never in tracked code:
`--state-dir` > `$ATLAS_DEV_WORKFLOW_HOME` > `<repo>/.atlas-dev-workflow/` (git-ignored).

| Path | Content |
|---|---|
| `config.json` | `atlas-devwf.config.v1` (validated on every load) |
| `state.sqlite3` | Durable state DB (schema version 1, WAL, forward-only migrations) |
| `merge_requests/` | Manual merge-gateway requests and confirmations |
| `exports/events.jsonl` | DevelopmentEvent export (derived; the journal is the source of truth) |
| `references.json` | Reference registry |

Task worktrees are created outside the source worktree under `worktrees_root`
(default `<repo>/../atlas-devwf-worktrees/devwf-<task_id>`), one branch `devwf/<task_id>` per task.

## Configuration (`config.json`)

| Key | Meaning |
|---|---|
| `project_id` | Must be `atlas-trading-expert` |
| `owner_policy` | `checkpoint_interval_s` (≤ 1800), `stale_after_s`, `reviewer_independence` (`distinct_provider` default, or `distinct_executor`), `max_provider_retries` (0-5) |
| `executors` | Catalog by name: `kind`, `provider`, `model`, `qualified_roles`, `enabled`, `timeout_s`, optional `argv`/`cwd`. No permission fields are accepted. |
| `role_chains` | Ordered failover chain per role, e.g. `"implementer": ["codex", "claude"]` |
| `control_authority` | Who may exercise each control action (default: owner for approve/reject/cancel; owner/operator for pause/resume/recover) |
| `lease_ttl_s`, `merge_gateway`, `worktrees_root`, `external_refs` | Runtime settings and the recorded design-PDF reference |

Real CLI executors ship **disabled**. The Owner enables them explicitly (`"enabled": true`) for authorized
local use. A disabled executor fails closed: `validate` reports `bindings_ok: false` and `run` refuses.
Defaults: Claude Code and Codex are peer coders (planner/implementer/QA/reviewer); Gemini is research-only.

## Task lifecycle

```
NEW_TASK -> PLANNING -> READY -> IMPLEMENTING -> TESTING -> REVIEW -> APPROVAL -> MERGE -> VERIFY -> DONE
                                     ^              |          |
                                     +-- FIXING <---+----------+   (bounded by max_fix_cycles, default 3, max 5)
Any active state -> PAUSED | BLOCKED | FAILED | CANCELLED
```

* Intake blocks fail closed before any agent call: activation requests, limited-live/real-money stages,
  protected branches, unauthorized legacy `atlas/` mutation, holdout access outside a preregistered grant,
  missing experiments, and **owned-path conflicts** with another lane that can still progress.
* Only `PROVIDER_UNAVAILABLE` blocks are resumable (operator holds use `pause`). Any other block is final for that
  task: register a successor TaskContract, then cancel the blocked task (the projection's `next_action` says
  exactly this). A non-resumable block releases its owned paths.
* APPROVAL auto-passes only for non-owner-sensitive Class A work; otherwise the Owner approves the exact head.
  Approval never enables activation. MERGE writes a PR request; the operator merges by the normal process and
  records it with `merge-confirm`. DONE is never strategy promotion.
* DONE requires the composed Definition of Done (owner + Atlas), recorded in the DONE transition evidence.

## Commands

All commands print JSON. Prefix: `python3 -m tools.atlas_dev_workflow [--state-dir DIR] [--repo ROOT]`.

| Command | Purpose |
|---|---|
| `init [--probe-versions]` | Create state dir, DB and default config; list locally installed CLIs (never installs) |
| `validate [--contract FILE]` | Validate config/chains/independence; classify a contract and show its gates |
| `task create FILE` / `task list` / `task show ID` | Intake and inspect tasks |
| `run [ID] [--max-steps N]` | Advance one task, or all runnable tasks in priority order, until wait/stop |
| `pause\|resume\|cancel ID [--actor A] [--reason R]` | Operator controls (checkpoints on pause/cancel) |
| `approvals [--pending]`, `approve\|reject APR --by owner [--note N]` | Owner approval gate |
| `merge-confirm ID --merged-head SHA --merge-ref REF` | Record the operator's merge of the requested PR |
| `monitor [ID]` | Owner-policy monitoring projection(s) for the Command Center (read-only) |
| `events [ID] [--out FILE]` | Idempotent DevelopmentEvent JSONL export |
| `control FILE` | Apply an abstract `control-request.v1` file under Atlas's authority table |
| `checkpoint ID [--trigger context_switch\|handoff\|stop\|risky_command]` | Durable checkpoint before switching context or handing off |
| `journal [ID] [--tail N] [--verify]`, `replay ID`, `recover [--run]` | Evidence, replay and post-restart recovery |
| `research ID --file F --source S` | Attach untrusted research as planner evidence (no authority) |
| `refs build [--no-legacy]`, `refs query TEXT` | Reference registry |
| `glossary [TERM]` | Owner + Atlas vocabulary |
| `simulate [--scenario happy\|test-failure\|review-reject\|fix-exhaustion]` | Dry run in a throwaway repo |

## Procedures

**Start a task.** `init` once → enable chosen executors in `config.json` → `validate` (must show
`bindings_ok: true`) → `validate --contract task.json` → `task create task.json` → `run TASK`.

**Continue after any interruption (no chat history needed).** `recover` (journal verify + replay check) →
`monitor TASK` → execute its `next_action`. The latest checkpoint (`journal TASK`, event `checkpoint`) holds the
exact HEAD, state, owned paths, diff summary, test commands/results, blockers and risks.

**Provider usage/auth/rate-limit exhaustion.** Automatic: the supervisor checkpoints, journals
`provider_failover` with the handoff digest, and hands the identical handoff to the next executor in the role
chain. If the whole chain is exhausted the task is `BLOCKED(PROVIDER_UNAVAILABLE)` with a checkpoint; when a
provider is available again, `resume TASK` then `run TASK`.

**Reviewer independence.** The reviewer is chosen from the reviewer chain excluding every executor (or
provider, under `distinct_provider`) that produced an accepted implementation for the task. If none remains,
the task blocks with `REVIEWER_NOT_INDEPENDENT`; add an independent reviewer to `role_chains` and register a
successor task.

**Budgets and effort.** Optional contract `budget` (`max_total_tokens`, `max_cost_usd_micros`,
`max_compute_ms`) stops work with `BUDGET_EXCEEDED` before the next agent call, using provider-reported usage
only (local CLIs currently report none, shown as `usage.reported: false`). Effort defaults to
A→`routine`, B→`standard`, C or `architecture_significant`→`deep`; `effort_override` changes reasoning depth
only.

**Command Center integration.** The Command Center may run `monitor`, read `exports/events.jsonl`, and drop
`control-request.v1` files for an operator to apply with `control`. Atlas validates, authorizes against
`control_authority`, journals and enforces every request; a repeated `request_id` is not re-applied.

## Qualification

```
python3 -m unittest discover -s tests/dev_workflow      # workflow runtime + owner policy
python3 -m unittest discover -s tests/atlas2            # atlas2 regression (must stay green, untouched)
```

Tests use only synthetic executors, scratch Git repos and an injectable clock: no model, broker, network or
credentials.
