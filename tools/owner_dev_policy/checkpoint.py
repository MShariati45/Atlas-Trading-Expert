"""Durable checkpoint contract: everything a successor needs to continue without the previous chat.

A checkpoint is written at least every `checkpoint_interval_s` (default 30 min) of active work and before
any risky command, context switch, provider exhaustion, handoff, stop, block or wait. A compressed
handoff may drop prose but never the exact HEAD, state, owned paths, tests, blockers or next action.
"""
from __future__ import annotations

from typing import Any, Mapping

from .schema import (SHA_RE, SchemaError, choice, integer, keys, obj, optional_string, single_action, string,
                     strings)

CHECKPOINT_V1 = "owner-dev-policy.checkpoint.v1"
DEFAULT_INTERVAL_S = 30 * 60
TRIGGERS = ("interval", "risky_command", "context_switch", "provider_exhausted", "handoff", "stop", "blocked",
            "waiting", "terminal")

_REQUIRED = {"schema_version", "project_id", "task_id", "trigger", "state", "head_sha", "base_sha", "branch",
             "owned_paths", "diff_summary", "commands", "blockers", "risks", "next_action", "created_us"}
_OPTIONAL = {"worktree", "executor"}


def validate_checkpoint(raw: Any) -> dict[str, Any]:
    data = obj(raw, "checkpoint")
    keys(data, "checkpoint", _REQUIRED, _OPTIONAL)
    if data["schema_version"] != CHECKPOINT_V1:
        raise SchemaError(f"checkpoint: unsupported schema_version {data['schema_version']!r}")
    string(data["project_id"], "checkpoint.project_id")
    string(data["task_id"], "checkpoint.task_id")
    choice(data["trigger"], "checkpoint.trigger", TRIGGERS)
    string(data["state"], "checkpoint.state")
    string(data["head_sha"], "checkpoint.head_sha", pattern=SHA_RE)
    string(data["base_sha"], "checkpoint.base_sha", pattern=SHA_RE)
    string(data["branch"], "checkpoint.branch")
    optional_string(data.get("worktree"), "checkpoint.worktree")
    optional_string(data.get("executor"), "checkpoint.executor")
    strings(data["owned_paths"], "checkpoint.owned_paths", nonempty=True)
    strings(data["diff_summary"], "checkpoint.diff_summary")
    strings(data["blockers"], "checkpoint.blockers")
    strings(data["risks"], "checkpoint.risks")
    if not isinstance(data["commands"], list):
        raise SchemaError("checkpoint.commands: expected list")
    for i, cmd in enumerate(data["commands"]):
        c = obj(cmd, f"checkpoint.commands[{i}]")
        keys(c, f"checkpoint.commands[{i}]", {"command", "result"})
        string(c["command"], f"checkpoint.commands[{i}].command")
        string(c["result"], f"checkpoint.commands[{i}].result")
    single_action(data["next_action"], "checkpoint.next_action")
    integer(data["created_us"], "checkpoint.created_us", 0, 2**63 - 1)
    return dict(data)


def make_checkpoint(*, project_id: str, task_id: str, trigger: str, state: str, head_sha: str, base_sha: str,
                    branch: str, owned_paths: list[str], next_action: str, created_us: int,
                    worktree: str | None = None, executor: str | None = None, diff_summary: list[str] = (),
                    commands: list[Mapping[str, str]] = (), blockers: list[str] = (),
                    risks: list[str] = ()) -> dict[str, Any]:
    cp = {"schema_version": CHECKPOINT_V1, "project_id": project_id, "task_id": task_id, "trigger": trigger,
          "state": state, "head_sha": head_sha, "base_sha": base_sha, "branch": branch,
          "owned_paths": list(owned_paths), "diff_summary": list(diff_summary),
          "commands": [dict(c) for c in commands], "blockers": list(blockers), "risks": list(risks),
          "next_action": next_action, "created_us": created_us}
    if worktree is not None:
        cp["worktree"] = worktree
    if executor is not None:
        cp["executor"] = executor
    return validate_checkpoint(cp)


def checkpoint_due(last_checkpoint_us: int | None, now_us: int, interval_s: int = DEFAULT_INTERVAL_S) -> bool:
    return last_checkpoint_us is None or now_us - last_checkpoint_us >= interval_s * 1_000_000
