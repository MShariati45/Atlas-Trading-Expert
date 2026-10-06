"""Canonical durable task states and the deterministic legal-transition table."""
from __future__ import annotations

from enum import StrEnum

from .errors import IllegalTransition


class State(StrEnum):
    NEW_TASK = "NEW_TASK"
    PLANNING = "PLANNING"
    READY = "READY"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    REVIEW = "REVIEW"
    FIXING = "FIXING"
    APPROVAL = "APPROVAL"
    MERGE = "MERGE"
    VERIFY = "VERIFY"
    DONE = "DONE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({State.DONE, State.FAILED, State.CANCELLED})
# States in which the supervisor may invoke a role or perform a gate step.
ACTIVE = frozenset({
    State.NEW_TASK, State.PLANNING, State.READY, State.IMPLEMENTING, State.TESTING,
    State.REVIEW, State.FIXING, State.APPROVAL, State.MERGE, State.VERIFY,
})

_FORWARD: dict[State, frozenset[State]] = {
    State.NEW_TASK: frozenset({State.PLANNING}),
    State.PLANNING: frozenset({State.READY}),
    State.READY: frozenset({State.IMPLEMENTING}),
    State.IMPLEMENTING: frozenset({State.TESTING}),
    State.TESTING: frozenset({State.REVIEW, State.FIXING}),
    State.REVIEW: frozenset({State.APPROVAL, State.FIXING}),
    State.FIXING: frozenset({State.TESTING}),
    State.APPROVAL: frozenset({State.MERGE}),
    State.MERGE: frozenset({State.VERIFY}),
    State.VERIFY: frozenset({State.DONE}),
}

# BLOCKED is recoverable only by an explicit operator resume to the recorded origin state, and only for
# outages. Every other block code is final for the task (register a successor task). Operator holds use PAUSED.
BLOCK_CODES_RECOVERABLE = frozenset({"PROVIDER_UNAVAILABLE"})


def legal_targets(source: State) -> frozenset[State]:
    if source in TERMINAL:
        return frozenset()
    if source is State.PAUSED:
        return frozenset(ACTIVE) | {State.CANCELLED}
    if source is State.BLOCKED:
        return frozenset(ACTIVE) | {State.CANCELLED}
    return _FORWARD[source] | {State.PAUSED, State.BLOCKED, State.FAILED, State.CANCELLED}


def validate_transition(source: State | str, target: State | str, *, origin: State | str | None = None) -> None:
    """Raise IllegalTransition unless source->target is legal.

    Leaving PAUSED/BLOCKED is legal only back to the recorded origin state.
    """
    try:
        src, dst = State(source), State(target)
    except ValueError as exc:
        raise IllegalTransition(f"unknown state: {exc}") from None
    if dst not in legal_targets(src):
        raise IllegalTransition(f"illegal transition {src} -> {dst}")
    if src in (State.PAUSED, State.BLOCKED) and dst is not State.CANCELLED:
        if origin is None or State(origin) is not dst:
            raise IllegalTransition(f"{src} may only resume to its origin state ({origin}), not {dst}")
