# Atlas v2 Agent Rules

Owner: Ali Shariati

## Project boundary
Work only inside this Atlas repository unless a task explicitly names another Atlas file.
Do not read, write, search, import, invoke, or modify Sigma WorkOffice, Alpha Lead Engine, or any unrelated project.
Do not stop or reconfigure their processes.

## Source of truth
Use `docs/atlas2/README.md`, the six ADRs, and `docs/atlas2/P0_ARCHITECTURE_FREEZE_ADDENDUM_2026-10-01.md` as the implementation contract.
The canonical design PDF is recorded there by path and SHA-256.
Legacy `atlas/` is evidence/reference only during P0 and must not be modified.

## Engineering rules
Keep atlas2 modular, boring, typed, deterministic, and easy to test.
No spaghetti wiring, hidden coupling, duplicate logic, speculative abstractions, or future-SaaS infrastructure.
Prefer the smallest correct implementation.
Keep P0 execution-free: no broker SDK, order sending, execution transport, live trading path, or secret handling.
No paid dependency/service and no network-dependent implementation without owner approval.

## Agent workflow
One bounded task at a time. Do not recursively delegate work to other agents.
Do not claim PASS without running the named test.
Do not silently fill missing trading semantics; mark the gap and keep it non-blocking where the design says so.
Do not commit, push, merge, open PRs, modify remotes, or change GitHub unless explicitly instructed by the owner/integration room.
Leave a concise summary of files changed, tests run, failures, and unresolved questions.
