"""Executor/provider qualification, failover chains and reviewer independence.

Coding providers are peers, not a fixed hierarchy: each role has an ordered fallback chain in config.
Provider/model identity never implies operational permission: permissions come only from the
project's role profiles, so an executor spec cannot carry any permission/authority field.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .schema import SchemaError, boolean, choice, integer, keys, obj, string, strings

ROLES = ("planner", "implementer", "qa", "reviewer", "research")
CODING_ROLES = frozenset({"implementer"})
INDEPENDENCE_RULES = ("distinct_executor", "distinct_provider")

_SPEC_REQUIRED = {"kind", "provider", "model", "qualified_roles"}
_SPEC_OPTIONAL = {"enabled", "timeout_s", "argv", "cwd"}
_AUTHORITY_WORDS = re.compile(r"(?i)permission|authority|privilege|approve|merge|admin|activation")

# Usage/auth/rate-limit exhaustion: no same-provider retry; checkpoint, then hand off to the successor.
_EXHAUSTION = re.compile(r"(?i)usage limit|rate.?limit|quota|insufficient credit|credit balance|unauthori[sz]ed|"
                         r"not logged in|login required|authentication|\b401\b|\b403\b|\b429\b")


def default_executors() -> dict[str, dict[str, Any]]:
    """Locally available providers. Real CLI executors ship disabled; the Owner enables them explicitly.

    Claude Code and Codex are peer coding executors. Gemini is qualified for research only unless a
    project adapter explicitly qualifies it for another role.
    """
    def cli(provider: str, roles: list[str]) -> dict[str, Any]:
        return {"kind": "cli", "provider": provider, "model": "default", "enabled": False, "timeout_s": 1800,
                "qualified_roles": roles}
    peer = ["planner", "implementer", "qa", "reviewer"]
    return {"claude": cli("claude", peer), "codex": cli("codex", peer), "gemini": cli("gemini", ["research"])}


def default_role_chains() -> dict[str, list[str]]:
    return {"planner": ["claude", "codex"], "implementer": ["codex", "claude"], "qa": ["claude", "codex"],
            "reviewer": ["claude", "codex"]}


def validate_executor_spec(name: str, raw: Any) -> Mapping[str, Any]:
    where = f"executors.{name}"
    spec = obj(raw, where)
    granted = [k for k in spec if _AUTHORITY_WORDS.search(k)]
    if granted:
        raise SchemaError(f"{where}: provider/model identity never carries operational permission ({granted})")
    keys(spec, where, _SPEC_REQUIRED, _SPEC_OPTIONAL)
    string(spec["kind"], f"{where}.kind")
    string(spec["provider"], f"{where}.provider")
    string(spec["model"], f"{where}.model")
    strings(spec["qualified_roles"], f"{where}.qualified_roles", allowed=frozenset(ROLES), nonempty=True)
    if "enabled" in spec:
        boolean(spec["enabled"], f"{where}.enabled")
    if "timeout_s" in spec:
        integer(spec["timeout_s"], f"{where}.timeout_s", 1, 24 * 3600)
    return spec


def validate_role_chains(executors: Mapping[str, Any], chains: Mapping[str, Any], required_roles: Iterable[str]) -> None:
    """Every required role has a non-empty, duplicate-free chain of executors qualified for that role."""
    for name, spec in executors.items():
        validate_executor_spec(name, spec)
    for role in required_roles:
        chain = strings(chains.get(role, []), f"role_chains.{role}", nonempty=True)
        if len(set(chain)) != len(chain):
            raise SchemaError(f"role_chains.{role}: duplicate executor")
        for name in chain:
            if name not in executors:
                raise SchemaError(f"role_chains.{role}: unknown executor {name!r}")
            if role not in executors[name]["qualified_roles"]:
                raise SchemaError(f"role_chains.{role}: executor {name!r} is not qualified for {role}")
    if unknown := sorted(set(chains) - set(ROLES)):
        raise SchemaError(f"role_chains: unknown role(s) {unknown}")


class Identity(Protocol):
    provider: str

    @property
    def executor_id(self) -> str: ...


def independent(candidate: Identity, implementers: Iterable[Identity], rule: str) -> bool:
    """A reviewer is independent only from every executor that implemented the task (incl. failover successors)."""
    choice(rule, "reviewer_independence", INDEPENDENCE_RULES)
    for impl in implementers:
        if rule == "distinct_executor" and candidate.executor_id == impl.executor_id:
            return False
        if rule == "distinct_provider" and candidate.provider == impl.provider:
            return False
    return True


def independent_reviewers(chain: Sequence[Identity], implementers: Sequence[Identity], rule: str) -> list[Identity]:
    return [c for c in chain if independent(c, implementers, rule)]


def validate_chain_independence(impl_chain: Sequence[Identity], reviewer_chain: Sequence[Identity], rule: str) -> None:
    """Whichever implementer in the chain ends up working, an independent reviewer must exist."""
    for impl in impl_chain:
        if not independent_reviewers(reviewer_chain, [impl], rule):
            raise SchemaError(f"no reviewer in the chain is independent from implementer {impl.executor_id} ({rule})")


def is_exhaustion(message: str) -> bool:
    return bool(_EXHAUSTION.search(message))
