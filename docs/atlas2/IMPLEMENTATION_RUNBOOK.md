# Atlas v2 Implementation Runbook

Owner: Ali Shariati

## Model roles
- Integration/Chief review: main room.
- Codex: bounded implementation tasks in the Atlas repo only.
- Claude: independent read-only review of completed bounded tasks.
- No agent-to-agent recursive loops.

## Isolation
Sigma WorkOffice automation runs independently under its own paths/processes. Atlas agents must never touch Sigma paths, environments, ports, repositories, or process controls.

## Fast path
P0-1 Core contracts → P0-2 Store → P0-3 Registry/Holdout → P0-4 Data/HTF → P0-5 Labels → P0-6 Capture → P0-7 Evaluate/Replay → P0-8 Conditional legacy import → P0-9 Hardening → P1 Shadow → P2 Demo → Limited Live Candidate.

Each stage: implement a small vertical slice, run deterministic tests, independent review, fix only confirmed issues, then advance.

## Agent invocation isolation

Atlas Codex runs must use `--ignore-user-config` so global MCP/plugin configuration cannot start or consult another project's index.

Atlas Claude reviews must use `--safe-mode --restricted --strict-mcp-config` and a read-only tool list unless a bounded implementation task explicitly requires edits.

Before and after each agent run, verify the Sigma automation PIDs remain untouched and no Atlas child process points at a Sigma path. Any accidental cross-project helper is terminated and its local tool artifacts are removed before work continues.

## Upgradeability gate

Before closing each stage, verify that the next stage can be added without rewriting the closed stage. Any semantic change must have a versioned contract or forward migration path. Compatibility bridges must be explicit, tested, and temporary.
