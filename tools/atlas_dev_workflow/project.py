"""Atlas project adapter for the Owner Development Policy.

Binds owner-level concepts to Atlas: project identity, Atlas vocabulary, effort by Atlas task class,
responsible role per state, the one executable next action, and who may exercise each control action.
Atlas domain gates (A/B/C, experiment/holdout/taint, no-live) stay in policy.py and only add obligations.
"""
from __future__ import annotations

from typing import Any, Mapping

from tools.owner_dev_policy.compute import resolve_effort
from tools.owner_dev_policy.glossary import compose_glossary

from .states import BLOCK_CODES_RECOVERABLE, TERMINAL, State

PROJECT_ID = "atlas-trading-expert"
CLI = "python3 -m tools.atlas_dev_workflow"

ATLAS_GLOSSARY = {
    "h4 last impulse": ("Atlas H4 Last Impulse semantics; owner-sensitive strategy semantics (Class B+).", ()),
    "holdout": ("Protected evaluation data; exposure only via a preregistered experiment and an instrument x "
                "interval grant.", ()),
    "taint": ("Marking of evidence that is not point-in-time or was produced after protected exposure; tainted "
              "evidence is never operational proof.", ()),
    "task class": ("Atlas risk class A (engineering), B (evidence/research semantics) or C (risk/execution/legacy). "
                   "The declared class is a floor and is never downgraded.", ("class a", "class b", "class c")),
    "baseline": ("The retained comparison arm of an experiment; never overwritten by a challenger.", ()),
    "challenger": ("A preregistered candidate compared against the retained baseline.", ()),
    "promotion": ("Strategy promotion. Never performed by the development workflow; development DONE is not "
                  "promotion.", ()),
    "activation": ("Enabling Demo/Live execution. Never performed by the development workflow; merge is not "
                   "activation.", ()),
}
GLOSSARY = compose_glossary(ATLAS_GLOSSARY)

EFFORT_BY_CLASS = {"A": "routine", "B": "standard", "C": "deep"}

RESPONSIBLE_ROLE = {
    State.NEW_TASK: "supervisor", State.PLANNING: "planner", State.READY: "supervisor",
    State.IMPLEMENTING: "implementer", State.FIXING: "implementer", State.TESTING: "qa", State.VERIFY: "qa",
    State.REVIEW: "reviewer", State.APPROVAL: "owner", State.MERGE: "owner", State.PAUSED: "owner",
    State.BLOCKED: "owner",
}

# Default authority table for abstract control requests. Overridable only in the project's own config.
DEFAULT_CONTROL_AUTHORITY: dict[str, list[str]] = {
    "pause": ["owner", "operator"], "resume": ["owner", "operator"], "cancel": ["owner"],
    "approve": ["owner"], "reject": ["owner"], "recover": ["owner", "operator"],
}


def effort_for(task_class: str, *, architecture_significant: bool, override: str | None) -> str:
    default = "deep" if architecture_significant else EFFORT_BY_CLASS[task_class]
    return resolve_effort(default, override)


def next_action(task: Mapping[str, Any], *, pending_approvals: list[str], merge_requested: bool) -> str:
    """Exactly one executable next action for a task, derived from durable state only."""
    state, tid = State(task["state"]), task["task_id"]
    if state in TERMINAL:
        return f"none: task is terminal ({state.value})"
    if state is State.PAUSED:
        return f"{CLI} resume {tid}"
    if state is State.BLOCKED:
        if task["block_code"] in BLOCK_CODES_RECOVERABLE:
            return f"{CLI} resume {tid}"
        return (f"{CLI} task show {tid}  # Owner decision: register a successor TaskContract resolving "
                f"{task['block_code']}, then cancel {tid}")
    if state is State.APPROVAL and pending_approvals:
        return f"{CLI} approve {pending_approvals[0]} --by owner  # after reviewing head {task['head_sha']}"
    if state is State.MERGE and merge_requested:
        return (f"{CLI} merge-confirm {tid} --merged-head <sha> --merge-ref <ref>  # after merging the requested "
                f"PR for head {task['approved_head_sha']}")
    return f"{CLI} run {tid}"
