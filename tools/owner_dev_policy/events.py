"""DevelopmentEvent contract: project-owned, append-only, idempotent, redacted workflow events.

The project's own durable journal is the source of truth. Events are a derived export for graph tools
and the Personal Command Center, which are consumers/projections only. `event_id` is a pure function of
(project_id, source_ref), so re-exporting the same journal entry always yields the same event.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .compute import USAGE_FIELDS, USAGE_MAX
from .redaction import bounded_excerpt, redact
from .schema import (SHA_RE, SchemaError, canonical_json, digest, integer, keys, obj, optional_string, string,
                     strings)

EVENT_V1 = "owner-dev-policy.event.v1"
SUMMARY_CHARS = 500

_REQUIRED = {"schema_version", "project_id", "run_id", "event_id", "event_type", "timestamp_us", "actor",
             "source_ref", "summary", "artifact_refs", "parent_event_ids", "decision_ids", "test_refs",
             "review_refs"}
_OPTIONAL = {"from_state", "to_state", "branch", "worktree", "head_sha", "usage"}


def event_id_for(project_id: str, source_ref: str) -> str:
    return "ev_" + digest(EVENT_V1, {"project_id": project_id, "source_ref": source_ref})[:32]


def validate_event(raw: Any) -> dict[str, Any]:
    data = obj(raw, "event")
    keys(data, "event", _REQUIRED, _OPTIONAL)
    if data["schema_version"] != EVENT_V1:
        raise SchemaError(f"event: unsupported schema_version {data['schema_version']!r}")
    for k in ("project_id", "run_id", "event_type", "source_ref"):
        string(data[k], f"event.{k}")
    if data["event_id"] != event_id_for(data["project_id"], data["source_ref"]):
        raise SchemaError("event.event_id: not derived from (project_id, source_ref)")
    integer(data["timestamp_us"], "event.timestamp_us", 0, 2**63 - 1)
    actor = obj(data["actor"], "event.actor")
    keys(actor, "event.actor", {"role"}, {"agent", "provider"})
    string(actor["role"], "event.actor.role")
    optional_string(actor.get("agent"), "event.actor.agent")
    optional_string(actor.get("provider"), "event.actor.provider")
    summary = string(data["summary"], "event.summary", empty=True)
    if len(summary) > SUMMARY_CHARS + 40 or redact(summary) != summary:
        raise SchemaError("event.summary: must be bounded and redacted")
    for k in ("artifact_refs", "parent_event_ids", "decision_ids", "test_refs", "review_refs"):
        strings(data[k], f"event.{k}")
    for k in ("from_state", "to_state", "branch", "worktree"):
        optional_string(data.get(k), f"event.{k}")
    optional_string(data.get("head_sha"), "event.head_sha", pattern=SHA_RE)
    if data.get("usage") is not None:
        usage = obj(data["usage"], "event.usage")
        keys(usage, "event.usage", set(), set(USAGE_FIELDS))
        for k, v in usage.items():
            integer(v, f"event.usage.{k}", 0, USAGE_MAX)
    return dict(data)


def make_event(*, project_id: str, run_id: str, source_ref: str, event_type: str, timestamp_us: int,
               actor_role: str, summary: str, actor_agent: str | None = None, actor_provider: str | None = None,
               from_state: str | None = None, to_state: str | None = None, branch: str | None = None,
               worktree: str | None = None, head_sha: str | None = None, artifact_refs: Iterable[str] = (),
               parent_event_ids: Iterable[str] = (), decision_ids: Iterable[str] = (), test_refs: Iterable[str] = (),
               review_refs: Iterable[str] = (), usage: Mapping[str, int] | None = None) -> dict[str, Any]:
    actor = {"role": actor_role}
    if actor_agent is not None:
        actor["agent"] = actor_agent
    if actor_provider is not None:
        actor["provider"] = actor_provider
    event: dict[str, Any] = {
        "schema_version": EVENT_V1, "project_id": project_id, "run_id": run_id,
        "event_id": event_id_for(project_id, source_ref), "event_type": event_type, "timestamp_us": timestamp_us,
        "actor": actor, "source_ref": source_ref,
        # Re-redact after bounding: a cut can split a "[REDACTED]" marker; redact() is idempotent after that.
        "summary": redact(bounded_excerpt(summary, SUMMARY_CHARS)),
        "artifact_refs": sorted(set(artifact_refs)), "parent_event_ids": list(parent_event_ids),
        "decision_ids": sorted(set(decision_ids)), "test_refs": sorted(set(test_refs)),
        "review_refs": sorted(set(review_refs))}
    optional = {"from_state": from_state, "to_state": to_state, "branch": branch, "worktree": worktree,
                "head_sha": head_sha, "usage": dict(usage) if usage else None}
    event.update({k: v for k, v in optional.items() if v is not None})
    return validate_event(event)


def new_events(existing: Iterable[Mapping[str, Any]], candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Idempotent merge: return only unseen events; a known id with different content is a hard error."""
    seen = {e["event_id"]: canonical_json(e) for e in existing}
    out = []
    for event in candidates:
        event = validate_event(event)
        known = seen.get(event["event_id"])
        if known is None:
            seen[event["event_id"]] = canonical_json(event)
            out.append(event)
        elif known != canonical_json(event):
            raise SchemaError(f"event {event['event_id']} already exported with different content")
    return out


def append_jsonl(path: str | Path, events: Iterable[Mapping[str, Any]]) -> int:
    """Append unseen events to a JSONL export file; re-running with the same events appends nothing."""
    path = Path(path)
    existing = []
    if path.exists():
        existing = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    fresh = new_events(existing, events)
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for event in fresh:
                fh.write(canonical_json(event) + "\n")
    return len(fresh)
