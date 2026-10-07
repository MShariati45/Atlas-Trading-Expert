# Development Workflow Reference

Status: qualified Atlas development workflow on branch feat/atlas-agentic-dev-workflow.

## Project boundary

Atlas Trading Expert is an independent trading product with its own runtime, UI, data, users/access, evaluation and deployment domains. The Personal Command Center is only the owner's development monitoring/control plane.

Development DONE never means strategy promotion, Demo activation, Live activation, or real-money permission.

## Canonical development flow

NEW_TASK -> PLANNING -> READY -> IMPLEMENTING -> TESTING -> REVIEW -> APPROVAL -> MERGE -> VERIFY -> DONE

FIXING is the bounded remediation loop. PAUSED, BLOCKED, FAILED, and CANCELLED are explicit fail-safe states.

## Roles

1. Development Supervisor / Orchestrator
2. Planner / Architect
3. Implementation Agent
4. QA / Test Agent
5. Independent Reviewer

## Atlas overlay

The generic owner development policy composes with Atlas-specific gates:
- strategy assumptions remain hypotheses
- research/backtest evidence has provenance
- protected experiment/HOLDOUT rules are not bypassed
- no development workflow can activate live trading
- risk/execution/strategy changes require Atlas-classified review and approval
- merge is not deployment or trading activation

## Provider model

Provider/model identity grants no authority. Provider exhaustion/auth/rate limits checkpoint and fail over according to config. Reviewer independence is enforced across accepted implementers.

## Durable coordination

Atlas stores project-owned workflow state, journal/evidence, approvals, attempts/fix cycles, exact Git identity, checkpoints, and monitoring projections. Replay and idempotency protect recovery and external mutations.

## Command Center

Generic workflow ID: atlas-development.

Command Center uses a write-denied, network-denied read-only projection path. Owner controls are sent as abstract requests with requested_by=owner and channel=command-center. Atlas validates each action against its own authority table and journals the decision.

No live trading/product control is exposed by the Command Center bridge.

## Qualification reference

Implementation commit before this reference document: dbd87af7a5a67c7c718904cf5812109e8aef3c27.

Qualification included 125 development-workflow tests, 247 Atlas regression tests, and 694 full-suite tests plus 242 subtests, with independent review approved for the implementation stage.

The local workflow runtime is initialized under .atlas-dev-workflow and that mutable state is not source-controlled.
