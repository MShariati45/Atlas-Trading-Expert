"""Owner-level Definition of Done, composed with (never replaced by) a project-specific DoD."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

OWNER_DOD = (
    "qualification_passed",                  # required tests/qualification passed on the exact head
    "independent_review_passed",             # approved by an identity independent of every implementer
    "checkpoint_recorded",                   # exact durable checkpoint for the final head exists
    "no_open_must_fix_before_implementation",
    "integration_state_known",               # merged/verified head recorded; no ambiguous integration state
    "journal_reconstructable",               # journal verifies and replays to the durable state
    "maintainability_audit_passed",          # required for architecture-significant work; else vacuously true
)


@dataclass(frozen=True)
class DoneDecision:
    done: bool
    failed: tuple[str, ...]


def evaluate_done(owner_evidence: Mapping[str, bool], project_checks: Mapping[str, bool]) -> DoneDecision:
    """DONE only if every owner requirement and every project check is explicitly True.

    Missing evidence is a failure, never a default pass. A project cannot shadow an owner requirement and
    must supply at least one project-specific check.
    """
    failed = [k for k in OWNER_DOD if owner_evidence.get(k) is not True]
    failed += [f"owner_evidence.{k}: unknown requirement" for k in sorted(set(owner_evidence) - set(OWNER_DOD))]
    if not project_checks:
        failed.append("project_definition_of_done: no project checks supplied")
    for name, ok in sorted(project_checks.items()):
        if name in OWNER_DOD:
            failed.append(f"project.{name}: may not redefine an owner requirement")
        elif ok is not True:
            failed.append(f"project.{name}")
    return DoneDecision(not failed, tuple(failed))
