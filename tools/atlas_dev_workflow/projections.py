"""Views derived only from durable state (task row + journal + approvals + mutations + agent runs).

- checkpoints: built from durable state, so a successor continues from repo/evidence, never from chat
- monitoring projection: the owner-policy projection the Personal Command Center may display
- development events: idempotent export of the journal for Graphify/Command Center consumers

The journal stays the single source of truth; nothing here is read back as authority.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from tools.owner_dev_policy.checkpoint import make_checkpoint
from tools.owner_dev_policy.compute import add_usage, budget_exceeded
from tools.owner_dev_policy.events import event_id_for, make_event
from tools.owner_dev_policy.monitoring import PROJECTION_V1, validate_projection
from tools.owner_dev_policy.policy import OwnerDevelopmentPolicy

from .project import PROJECT_ID, RESPONSIBLE_ROLE, next_action
from .states import TERMINAL, State
from .store import Store

# Lease bookkeeping is concurrency mechanics, not a workflow event; it stays in the journal only.
NOT_EXPORTED = frozenset({"lease_acquired"})
_STEP_KEYS = ("step_key", "plan_step", "implementation_step", "qa_step", "review_step", "verify_step",
              "idempotency_key")


def _source_ref(entry: Mapping[str, Any]) -> str:
    return "journal:" + entry["entry_hash"]


def last_evidence(entries: list[dict[str, Any]], key: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    for entry in reversed(entries):
        evidence = entry["payload"].get("evidence") if entry["event_type"] == "transition" else None
        if evidence and key in evidence:
            return entry, evidence
    return None, {}


def last_entry(entries: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    return next((e for e in reversed(entries) if e["event_type"] == event_type), None)


def usage_totals(entries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return add_usage(e["payload"].get("usage") for e in entries if e["event_type"] == "agent_packet")


def _pending(store: Store, task_id: str) -> list[str]:
    return [a["approval_id"] for a in store.approvals(task_id=task_id, status="PENDING")]


def _merge_requested(store: Store, task_id: str) -> bool:
    return any(m["kind"] == "merge_request" and m["status"] == "REQUESTED" for m in store.mutations(task_id))


def task_next_action(store: Store, task: Mapping[str, Any]) -> str:
    return next_action(task, pending_approvals=_pending(store, task["task_id"]),
                       merge_requested=_merge_requested(store, task["task_id"]))


# -- checkpoints ----------------------------------------------------------------------------------

def checkpoint_for(store: Store, task_id: str, trigger: str, *, executor: str | None = None) -> dict[str, Any]:
    task = store.get_task(task_id)
    entries = store.journal_entries(task_id)
    contract = json.loads(task["contract_json"])
    classification = json.loads(task["classification_json"])
    _, impl = last_evidence(entries, "files_changed")
    _, qa = last_evidence(entries, "tests")
    risks = [f"owner-sensitive area: {a}" for a in classification["owner_sensitive"]]
    if any(e["payload"].get("context_truncated") for e in entries if e["event_type"] == "agent_packet"):
        risks.append("an agent step ran with truncated context (see agent_packet events)")
    return make_checkpoint(
        project_id=PROJECT_ID, task_id=task_id, trigger=trigger, state=task["state"],
        head_sha=task["head_sha"] or task["base_sha"], base_sha=task["base_sha"], branch=task["branch"],
        worktree=task["worktree_path"], executor=executor, owned_paths=contract["scope_paths"],
        diff_summary=impl.get("files_changed", []),
        commands=[{"command": t["command"], "result": f"{t['name']}: passed={t['passed']} failed={t['failed']}"}
                  for t in qa.get("tests", [])],
        blockers=[f"{task['block_code']}: {task['block_reason']}"] if task["state"] == State.BLOCKED else [],
        risks=risks, next_action=task_next_action(store, task), created_us=store.clock())


def record_checkpoint(store: Store, task_id: str, trigger: str, *, actor: str,
                      executor: str | None = None) -> tuple[bool, dict[str, Any]]:
    """Journal a checkpoint unless the latest one is identical apart from its timestamp.

    Returns (written, durable checkpoint): the new checkpoint, or the identical one already journaled.
    """
    cp = checkpoint_for(store, task_id, trigger, executor=executor)
    last = last_entry(store.journal_entries(task_id), "checkpoint")
    if last is not None and {**last["payload"], "created_us": 0} == {**cp, "created_us": 0}:
        return False, last["payload"]
    store.journal(task_id, "checkpoint", actor, cp)
    return True, cp


def last_checkpoint_us(store: Store, task: Mapping[str, Any]) -> int:
    last = last_entry(store.journal_entries(task["task_id"]), "checkpoint")
    return last["created_us"] if last is not None else task["created_us"]


# -- development events ---------------------------------------------------------------------------

def _actor(entry: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    if entry["event_type"] == "agent_packet":
        executor = entry["payload"]["executor_id"]
        return entry["payload"]["role"], executor, executor.split(":")[1]
    if entry["actor"] == "supervisor" or entry["actor"].startswith("worker"):
        return "supervisor", entry["actor"], None
    return "operator", entry["actor"], None


def _collect(value: Any, names: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for k, v in value.items():
            if k in names and isinstance(v, str):
                found.add(v)
            found |= _collect(v, names)
    elif isinstance(value, list):
        for v in value:
            found |= _collect(v, names)
    return found


def _summary(entry: Mapping[str, Any]) -> str:
    p = entry["payload"]
    if entry["event_type"] == "transition":
        return p["reason"]
    if entry["event_type"] == "agent_packet":
        return f"{p['role']} step {p['status']} via {p['executor_id']}"
    if entry["event_type"] == "checkpoint":
        return f"checkpoint ({p['trigger']}); next: {p['next_action']}"
    return entry["event_type"]


def export_events(store: Store, task_id: str | None = None) -> list[dict[str, Any]]:
    """Map journal entries to owner-policy DevelopmentEvents. Deterministic: same journal -> same events."""
    tasks = {t["task_id"]: t for t in store.list_tasks()}
    previous: dict[str, str] = {}
    git: dict[str, dict[str, str | None]] = {}
    out = []
    for entry in store.journal_entries(task_id):
        run = entry["task_id"]
        state_after = entry["payload"].get("state_after", {}) if entry["event_type"] == "transition" else {}
        g = git.setdefault(run, {"worktree": None, "head_sha": tasks[run]["base_sha"]})
        g.update({k: state_after[src] for k, src in (("worktree", "worktree_path"), ("head_sha", "head_sha"))
                  if state_after.get(src)})
        if entry["event_type"] in NOT_EXPORTED:
            continue
        role, agent, provider = _actor(entry)
        payload = entry["payload"]
        event = make_event(
            project_id=PROJECT_ID, run_id=run, source_ref=_source_ref(entry), event_type=entry["event_type"],
            timestamp_us=entry["created_us"], actor_role=role, actor_agent=agent, actor_provider=provider,
            from_state=entry["from_state"], to_state=entry["to_state"], branch=tasks[run]["branch"],
            worktree=g["worktree"], head_sha=g["head_sha"], summary=_summary(entry),
            artifact_refs=_collect(payload, _STEP_KEYS), decision_ids=_collect(payload, ("approval_id",)),
            test_refs=_collect(payload, ("qa_step", "verify_step")), review_refs=_collect(payload, ("review_step",)),
            parent_event_ids=[previous[run]] if run in previous else [], usage=payload.get("usage"))
        previous[run] = event["event_id"]
        out.append(event)
    return out


# -- monitoring projection ------------------------------------------------------------------------

def _health(task: Mapping[str, Any], waiting: bool, age_s: int, policy: OwnerDevelopmentPolicy, now_us: int) -> str:
    state = State(task["state"])
    if state in TERMINAL:
        return "terminal"
    if state is State.BLOCKED:
        return "blocked"
    if waiting or state is State.PAUSED:
        return "waiting"
    lease_dead = task["lease_owner"] is not None and (task["lease_expires_us"] or 0) <= now_us
    return "stale" if lease_dead or age_s >= policy.stale_after_s else "active"


def build_projection(store: Store, task_id: str, *, policy: OwnerDevelopmentPolicy) -> dict[str, Any]:
    task = store.get_task(task_id)
    now = store.clock()
    entries = store.journal_entries(task_id)
    contract = json.loads(task["contract_json"])
    state = State(task["state"])
    pending = _pending(store, task_id)
    merge_requested = _merge_requested(store, task_id)
    role = RESPONSIBLE_ROLE.get(state)
    runs = store.agent_runs(task_id)
    executor = next((r["executor_id"] for r in reversed(runs) if r["role"] == role), None)
    qa_entry, qa = last_evidence(entries, "tests")
    rev_entry, rev = last_evidence(entries, "review_step")
    qa_status = "NOT_RUN" if qa_entry is None else ("PASS" if qa_entry["to_state"] in ("REVIEW", "DONE") else "FAIL")
    totals = usage_totals(entries)
    budget = contract.get("budget")
    cp = last_entry(entries, "checkpoint")
    last_update = max([task["updated_us"]] + [e["created_us"] for e in entries])
    age_s = max(0, (now - last_update) // 1_000_000)
    waiting = (state is State.APPROVAL and bool(pending)) or (state is State.MERGE and merge_requested)
    exported = [e for e in entries if e["event_type"] not in NOT_EXPORTED]
    projection = {
        "schema_version": PROJECTION_V1, "project_id": PROJECT_ID, "run_id": task_id, "title": contract["title"],
        "state": state.value, "policy_class": task["task_class"], "priority": contract["priority"],
        "responsible": {"role": role, "executor": executor},
        "attempt": {"fix_cycle": task["fix_cycles"], "max_fix_cycles": task["max_fix_cycles"],
                    "agent_attempts": sum(r["attempts"] for r in runs)},
        "git": {"branch": task["branch"], "worktree": task["worktree_path"], "base_sha": task["base_sha"],
                "head_sha": task["head_sha"] or task["base_sha"], "approved_head_sha": task["approved_head_sha"]},
        "qualification": {"status": qa_status, "ref": None if qa_entry is None else _source_ref(qa_entry)},
        "review": {"status": rev.get("verdict", "NOT_RUN"), "ref": None if rev_entry is None else _source_ref(rev_entry),
                   "reviewer": rev.get("reviewer_executor")},
        "blockers": ([{"code": task["block_code"], "reason": task["block_reason"]}] if state is State.BLOCKED else []),
        "approvals_needed": pending,
        "usage": {"reported": bool(totals), "totals": totals, "budget": budget,
                  "exceeded": budget_exceeded(budget, totals)},
        "context_truncated": any(e["payload"].get("context_truncated") for e in entries
                                 if e["event_type"] == "agent_packet"),
        "last_checkpoint": None if cp is None else {
            "trigger": cp["payload"]["trigger"], "created_us": cp["created_us"], "head_sha": cp["payload"]["head_sha"],
            "next_action": cp["payload"]["next_action"], "event_ref": event_id_for(PROJECT_ID, _source_ref(cp))},
        "evidence_refs": [_source_ref(e) for e in entries if e["event_type"] == "transition" and e["payload"]["evidence"]],
        "next_action": next_action(task, pending_approvals=pending, merge_requested=merge_requested),
        "health": {"status": _health(task, waiting, age_s, policy, now), "last_update_us": last_update, "age_s": age_s},
        "terminal_result": state.value if state in TERMINAL else None,
        "last_event_id": event_id_for(PROJECT_ID, _source_ref(exported[-1])) if exported else None,
        "event_count": len(exported), "generated_us": now,
    }
    return validate_projection(projection)
