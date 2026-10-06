"""OwnerDevelopmentPolicy: the configurable owner-level settings a project runtime must honour.

Project domain policy (risk classes, research/evidence gates, release boundaries) is an additional overlay
supplied by the project adapter. It composes with this policy and can only add obligations, never remove them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from . import OWNER_POLICY_VERSION
from .checkpoint import DEFAULT_INTERVAL_S
from .providers import INDEPENDENCE_RULES
from .schema import choice, integer, keys, obj


@dataclass(frozen=True)
class OwnerDevelopmentPolicy:
    checkpoint_interval_s: int = DEFAULT_INTERVAL_S
    stale_after_s: int = 2 * 3600
    reviewer_independence: str = "distinct_provider"
    max_provider_retries: int = 2

    def __post_init__(self) -> None:
        integer(self.checkpoint_interval_s, "owner_policy.checkpoint_interval_s", 60, DEFAULT_INTERVAL_S)
        integer(self.stale_after_s, "owner_policy.stale_after_s", 60, 7 * 24 * 3600)
        choice(self.reviewer_independence, "owner_policy.reviewer_independence", INDEPENDENCE_RULES)
        integer(self.max_provider_retries, "owner_policy.max_provider_retries", 0, 5)

    @classmethod
    def from_dict(cls, raw: Any) -> "OwnerDevelopmentPolicy":
        data: Mapping[str, Any] = obj(raw, "owner_policy")
        keys(data, "owner_policy", set(), {"checkpoint_interval_s", "stale_after_s", "reviewer_independence",
                                           "max_provider_retries"})
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"version": OWNER_POLICY_VERSION}


def _overlap(a: str, b: str) -> bool:
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def owned_path_conflicts(paths: Iterable[str], other_lanes: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
    """Explicit file ownership: a new task lane may not own a path another active lane owns (or nests in)."""
    paths = list(paths)
    conflicts = {}
    for lane, owned in sorted(other_lanes.items()):
        hits = sorted({p for p in paths for o in owned if _overlap(p, o)})
        if hits:
            conflicts[lane] = hits
    return conflicts
