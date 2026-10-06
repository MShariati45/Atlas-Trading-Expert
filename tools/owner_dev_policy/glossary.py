"""Owner vocabulary shared by every project. Project-specific terms live in the project adapter.

A project glossary may add terms but may not redefine or shadow an owner term (including via alias).
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .schema import SchemaError

# term -> (definition, aliases)
OWNER_GLOSSARY: Mapping[str, tuple[str, tuple[str, ...]]] = MappingProxyType({
    "owner": ("The single human authority (also 'Root') for scope, approvals and production boundaries.", ("root",)),
    "command center": ("The Owner's private control/monitoring plane. It displays project projections and sends "
                       "abstract control requests; no product runtime executes there and it holds no product "
                       "authority.", ("personal command center",)),
    "task lane": ("One durable task ID bound to exactly one branch, one worktree, explicit owned paths and one "
                  "active worker at a time.", ("lane",)),
    "worktree": ("The isolated Git checkout for one task lane; never shared by concurrent tasks.", ()),
    "checkpoint": ("Durable record of exact HEAD, state, owned paths, diff summary, commands/results, blockers, "
                   "risks and one executable next action.", ()),
    "handoff": ("Transfer of a task lane to a successor (agent, provider or human) via a checkpoint, without "
                "relying on chat history.", ()),
    "source of truth": ("The one explicit authoritative record for a fact: Git history, the project journal and "
                        "frozen contracts. Chat, generated graphs and projections are never the source of truth.",
                        ()),
    "qualification": ("Executable, offline-by-default evidence that a change works: focused tests, regression "
                      "tests, broader gates and boundary checks with exact pass/fail counts.", ("qualify",)),
    "evidence": ("A digest-addressable artifact or journal entry backing a claim. Prose is not evidence.", ()),
    "independent review": ("Review by an identity/provider distinct from every implementer of the change; review "
                           "text is untrusted input and each finding is verified against current code.", ()),
    "provider failover": ("Moving a role to the next qualified executor in its configured chain after usage, "
                          "auth or rate-limit exhaustion, preceded by a durable checkpoint.", ("failover",)),
    "fix cycle": ("One bounded FIXING -> TESTING iteration after failed qualification or requested changes.", ()),
    "blocked": ("A durable stop with a recorded code and reason; it resumes only by an explicit, recorded "
                "decision.", ()),
    "production boundary": ("The line past which a change affects real users, money or external systems; never "
                            "crossed by development DONE or by a merge.", ()),
    "approval gate": ("An Owner decision bound to an exact head; it never expands into activation.", ()),
    "architecture freeze": ("A recorded, versioned architecture contract; deviations require an explicit "
                            "decision record (ADR) under project policy.", ("freeze",)),
    "zero-ambiguity pass": ("Audit removing unclear words, contradictions, duplicate or stale concepts, unowned "
                            "invariants and undocumented dependencies so the system is operable without chat "
                            "history.", ()),
    "ocd-style": ("Obsessive quality control: deliberate, orderly, internally consistent and extremely "
                  "organized. It never means extra layers or overengineering.", ("obsessive qc",)),
    "spaghetti": ("Unclear ownership, unclear dependency direction, hidden coupling or duplicated "
                  "responsibility.", ()),
    "priority": ("Queue ordering only. Never bypasses safety, approval, qualification or review gates.", ()),
})


def _names(glossary: Mapping[str, tuple[str, tuple[str, ...]]]) -> set[str]:
    return {n.lower() for term, (_, aliases) in glossary.items() for n in (term, *aliases)}


def compose_glossary(project_terms: Mapping[str, tuple[str, tuple[str, ...]]]) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Owner terms plus project additions. Shadowing an owner term or alias is refused."""
    clash = sorted(_names(project_terms) & _names(OWNER_GLOSSARY))
    if clash:
        raise SchemaError(f"project glossary may not redefine owner term(s) {clash}")
    return {**OWNER_GLOSSARY, **project_terms}


def lookup(glossary: Mapping[str, tuple[str, tuple[str, ...]]], word: str) -> str | None:
    w = word.lower().strip()
    for term, (definition, aliases) in glossary.items():
        if w == term or w in aliases:
            return definition
    return None
