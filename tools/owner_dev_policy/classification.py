"""Priority model and finding classification.

Priority orders the work queue. It never bypasses a safety, approval, qualification or review gate:
those gates are evaluated identically for every priority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .schema import SchemaError, choice, keys, obj, optional_string, string

# Highest first. The index is the queue rank.
PRIORITIES = (
    "CRITICAL_BLOCKER",
    "MUST_FIX_BEFORE_IMPLEMENTATION",
    "MUST_FIX_BEFORE_PRODUCTION",
    "HIGH",
    "NORMAL",
    "LOW",
    "ACCEPTABLE_TECHNICAL_DEBT",
    "DEFERRED_SCALE_CONCERN",
)
DEFAULT_PRIORITY = "NORMAL"
_RANK = {p: i for i, p in enumerate(PRIORITIES)}

# Classification for review, audit and zero-ambiguity findings.
FINDING_CLASSES = (
    "MUST_FIX_BEFORE_IMPLEMENTATION",  # blocks development DONE
    "MUST_FIX_BEFORE_PRODUCTION",      # does not block development DONE; blocks any production boundary
    "ACCEPTABLE_TECHNICAL_DEBT",       # recorded, owned, not blocking
    "DEFERRED_SCALE_CONCERN",          # recorded, revisit at scale, not blocking
)
# Review text is untrusted input: every finding is verified against current code before it is acted on.
DISPOSITIONS = ("OPEN", "FIXED", "REJECTED_INVALID", "ACCEPTED_DEBT", "DEFERRED")


def priority_rank(priority: str) -> int:
    return _RANK[choice(priority, "priority", PRIORITIES)]


def queue_order(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Order `{task_id, priority, created_us}` items: priority rank, then age, then id (deterministic)."""
    return sorted(items, key=lambda i: (priority_rank(i["priority"]), i["created_us"], i["task_id"]))


@dataclass(frozen=True)
class Finding:
    finding_id: str
    classification: str
    summary: str
    disposition: str = "OPEN"
    reason: str | None = None
    path: str | None = None

    @classmethod
    def from_dict(cls, raw: Any, where: str = "finding") -> "Finding":
        data = obj(raw, where)
        keys(data, where, {"finding_id", "classification", "summary"}, {"disposition", "reason", "path"})
        disposition = choice(data.get("disposition", "OPEN"), f"{where}.disposition", DISPOSITIONS)
        reason = optional_string(data.get("reason"), f"{where}.reason")
        if disposition in ("REJECTED_INVALID", "ACCEPTED_DEBT", "DEFERRED") and reason is None:
            raise SchemaError(f"{where}: disposition {disposition} requires a recorded reason")
        return cls(string(data["finding_id"], f"{where}.finding_id"),
                   choice(data["classification"], f"{where}.classification", FINDING_CLASSES),
                   string(data["summary"], f"{where}.summary"), disposition, reason,
                   optional_string(data.get("path"), f"{where}.path"))

    def to_dict(self) -> dict[str, Any]:
        out = {"finding_id": self.finding_id, "classification": self.classification, "summary": self.summary,
               "disposition": self.disposition}
        if self.reason is not None:
            out["reason"] = self.reason
        if self.path is not None:
            out["path"] = self.path
        return out


def blocks_development_done(finding: Finding) -> bool:
    return finding.classification == "MUST_FIX_BEFORE_IMPLEMENTATION" and finding.disposition == "OPEN"


def blocks_production(finding: Finding) -> bool:
    return finding.disposition == "OPEN" and finding.classification in (
        "MUST_FIX_BEFORE_IMPLEMENTATION", "MUST_FIX_BEFORE_PRODUCTION")
