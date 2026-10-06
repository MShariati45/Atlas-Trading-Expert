"""Monitoring projection and abstract control-request contracts for the Personal Command Center.

The Command Center is a separate private control/monitoring plane. It reads a project's projection and
may send abstract control requests. It never receives product-internal authority by displaying a
control: every request is validated and enforced (or refused) by the owning project, against the
project's own authority table, and the decision is journaled by the project.
"""
from __future__ import annotations

from typing import Any

from .classification import PRIORITIES
from .schema import (ID_RE, SHA_RE, SchemaError, boolean, choice, integer, keys, obj, optional_string,
                     single_action, string, strings)

PROJECTION_V1 = "owner-dev-policy.monitoring-projection.v1"
CONTROL_REQUEST_V1 = "owner-dev-policy.control-request.v1"
HEALTH = ("active", "waiting", "stale", "blocked", "terminal")
QUALIFICATION = ("NOT_RUN", "PASS", "FAIL")
REVIEW = ("NOT_RUN", "APPROVE", "REQUEST_CHANGES")
TERMINAL_RESULTS = ("DONE", "FAILED", "CANCELLED")
CONTROL_ACTIONS = ("pause", "resume", "cancel", "approve", "reject", "recover")

_PROJECTION_REQUIRED = {
    "schema_version", "project_id", "run_id", "title", "state", "policy_class", "priority", "responsible",
    "attempt", "git", "qualification", "review", "blockers", "approvals_needed", "usage", "context_truncated",
    "last_checkpoint", "evidence_refs", "next_action", "health", "terminal_result", "last_event_id",
    "event_count", "generated_us"}


def validate_projection(raw: Any) -> dict[str, Any]:
    p = obj(raw, "projection")
    keys(p, "projection", _PROJECTION_REQUIRED)
    if p["schema_version"] != PROJECTION_V1:
        raise SchemaError(f"projection: unsupported schema_version {p['schema_version']!r}")
    for k in ("project_id", "run_id", "title", "state", "policy_class"):
        string(p[k], f"projection.{k}")
    choice(p["priority"], "projection.priority", PRIORITIES)
    resp = obj(p["responsible"], "projection.responsible")
    keys(resp, "projection.responsible", {"role", "executor"})
    optional_string(resp["role"], "projection.responsible.role")
    optional_string(resp["executor"], "projection.responsible.executor")
    att = obj(p["attempt"], "projection.attempt")
    keys(att, "projection.attempt", {"fix_cycle", "max_fix_cycles", "agent_attempts"})
    for k in att:
        integer(att[k], f"projection.attempt.{k}", 0, 10**6)
    git = obj(p["git"], "projection.git")
    keys(git, "projection.git", {"branch", "worktree", "base_sha", "head_sha", "approved_head_sha"})
    string(git["branch"], "projection.git.branch")
    optional_string(git["worktree"], "projection.git.worktree")
    string(git["base_sha"], "projection.git.base_sha", pattern=SHA_RE)
    string(git["head_sha"], "projection.git.head_sha", pattern=SHA_RE)
    optional_string(git["approved_head_sha"], "projection.git.approved_head_sha", pattern=SHA_RE)
    q = obj(p["qualification"], "projection.qualification")
    keys(q, "projection.qualification", {"status", "ref"})
    choice(q["status"], "projection.qualification.status", QUALIFICATION)
    r = obj(p["review"], "projection.review")
    keys(r, "projection.review", {"status", "ref", "reviewer"})
    choice(r["status"], "projection.review.status", REVIEW)
    if not isinstance(p["blockers"], list):
        raise SchemaError("projection.blockers: expected list")
    for i, b in enumerate(p["blockers"]):
        keys(obj(b, f"projection.blockers[{i}]"), f"projection.blockers[{i}]", {"code", "reason"})
    strings(p["approvals_needed"], "projection.approvals_needed")
    if p["usage"] is not None:
        obj(p["usage"], "projection.usage")
    boolean(p["context_truncated"], "projection.context_truncated")
    if p["last_checkpoint"] is not None:
        cp = obj(p["last_checkpoint"], "projection.last_checkpoint")
        keys(cp, "projection.last_checkpoint", {"trigger", "created_us", "head_sha", "next_action", "event_ref"})
    strings(p["evidence_refs"], "projection.evidence_refs")
    single_action(p["next_action"], "projection.next_action")
    h = obj(p["health"], "projection.health")
    keys(h, "projection.health", {"status", "last_update_us", "age_s"})
    choice(h["status"], "projection.health.status", HEALTH)
    if p["terminal_result"] is not None:
        choice(p["terminal_result"], "projection.terminal_result", TERMINAL_RESULTS)
    optional_string(p["last_event_id"], "projection.last_event_id")
    integer(p["event_count"], "projection.event_count", 0, 10**9)
    integer(p["generated_us"], "projection.generated_us", 0, 2**63 - 1)
    return dict(p)


def validate_control_request(raw: Any) -> dict[str, Any]:
    """Abstract request only. There is deliberately no field that could carry authority or activation."""
    c = obj(raw, "control_request")
    keys(c, "control_request", {"schema_version", "project_id", "request_id", "action", "target", "requested_by",
                                "channel", "reason", "created_us"})
    if c["schema_version"] != CONTROL_REQUEST_V1:
        raise SchemaError(f"control_request: unsupported schema_version {c['schema_version']!r}")
    string(c["project_id"], "control_request.project_id")
    string(c["request_id"], "control_request.request_id", pattern=ID_RE)
    choice(c["action"], "control_request.action", CONTROL_ACTIONS)
    string(c["target"], "control_request.target", pattern=ID_RE)
    string(c["requested_by"], "control_request.requested_by")
    string(c["channel"], "control_request.channel")
    string(c["reason"], "control_request.reason", empty=True)
    integer(c["created_us"], "control_request.created_us", 0, 2**63 - 1)
    return dict(c)
