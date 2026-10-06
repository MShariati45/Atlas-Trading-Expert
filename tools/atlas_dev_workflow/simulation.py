"""Synthetic agents and scenario contracts for dry-run simulation and qualification.

No model API calls, no broker, no network: every role is a deterministic FakeExecutor and Git work
happens in a throwaway repository.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .contracts import PACKET_V1, TASK_CONTRACT_V1
from .errors import ProviderError
from .executors import FakeExecutor
from .roles import IMPLEMENTER, PLANNER, QA, REVIEWER

_GIT_ID = ["-c", "user.name=devwf-sim", "-c", "user.email=devwf-sim@example.invalid", "-c", "commit.gpgsign=false"]


def run_git(args: list[str], cwd: str | Path) -> str:
    return subprocess.run(["git", *_GIT_ID, *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def make_repo(root: str | Path) -> tuple[Path, str]:
    """Create a scratch repository with one commit on `integration`; returns (path, base_sha)."""
    repo = Path(root) / "repo"
    repo.mkdir(parents=True)
    run_git(["init", "-q", "-b", "integration"], repo)
    (repo / "README.md").write_text("scratch\n", encoding="utf-8")
    run_git(["add", "README.md"], repo)
    run_git(["commit", "-q", "-m", "base"], repo)
    return repo, run_git(["rev-parse", "HEAD"], repo)


def contract(task_id: str, base_sha: str, **overrides: Any) -> dict[str, Any]:
    data = {
        "schema_version": TASK_CONTRACT_V1, "task_id": task_id, "title": f"Scenario {task_id}",
        "objective": "Synthetic qualification scenario", "declared_class": "A", "impact_areas": ["refactor"],
        "scope_paths": ["atlas2/core"], "base_sha": base_sha, "target_branch": "integration",
        "acceptance": ["python3 -m unittest discover -s tests/atlas2"],
    }
    data.update(overrides)
    return data


def experiment(**overrides: Any) -> dict[str, Any]:
    data = {
        "experiment_id": "EXP-SIM-001", "prereg_digest": "a" * 64, "evaluator_digest": "b" * 64,
        "evaluator_frozen": True, "baseline": "baseline-v1 (owner baseline comparison arm)",
        "challenger": "challenger-v1", "search_set": ["challenger-v1"], "dataset_windows": ["2019-2022 train", "2023 OOS"],
        "cost_model": "broker-native spread + commission v1", "holdout_rules": "instrument x interval grant only",
        "stopping_rules": "single preregistered inspection", "failed_result_persistence": True,
    }
    data.update(overrides)
    return data


def _packet(handoff: Mapping[str, Any], kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": PACKET_V1, "role": handoff["role"], "kind": kind, "task_id": handoff["task_id"],
            "step_key": handoff["step_key"], "payload": payload}


@dataclass
class Script:
    """Behaviour knobs for synthetic agents."""
    qa_fail_times: int = 0
    review_reject_times: int = 0
    provider_errors: dict[str, int] = field(default_factory=dict)  # role -> transient failures before success
    invalid_output: dict[str, int] = field(default_factory=dict)  # role -> malformed outputs before success
    plan_overrides: dict[str, Any] = field(default_factory=dict)
    boundary_overrides: dict[str, bool] = field(default_factory=dict)
    implementation_overrides: dict[str, Any] = field(default_factory=dict)
    extra_checks: dict[str, bool] = field(default_factory=dict)
    omit_checks: tuple[str, ...] = ()
    qa_flags: tuple[str, ...] = ()
    review_flags: tuple[str, ...] = ()
    review_overrides: dict[str, Any] = field(default_factory=dict)
    change_path: str | None = None
    usage: dict[str, Any] | None = None  # provider-reported usage attached to every synthetic response
    counters: dict[str, int] = field(default_factory=dict)

    def _bump(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def _transient(self, role: str) -> Any:
        if self.counters.get(f"{role}:perr", 0) < self.provider_errors.get(role, 0):
            self._bump(f"{role}:perr")
            return ProviderError(f"synthetic {role} provider outage")
        if self.counters.get(f"{role}:bad", 0) < self.invalid_output.get(role, 0):
            self._bump(f"{role}:bad")
            return "I think it went fine (no JSON packet)"
        return None

    def planner(self, h: Mapping[str, Any]) -> Any:
        if (t := self._transient(PLANNER)) is not None:
            return t
        c = h["contract"]
        payload = {"summary": f"plan for {c['task_id']}", "steps": ["implement", "test", "review"],
                   "proposed_class": c["declared_class"], "impact_areas": c["impact_areas"],
                   "semantics_change": c["declared_class"] != "A", "rollback": "revert task branch",
                   "baseline_retained": True, "risks": [], "references": [r["path"] for r in h["references"]]}
        payload.update(self.plan_overrides)
        return _packet(h, "plan", payload)

    def implementer(self, h: Mapping[str, Any]) -> Any:
        if (t := self._transient(IMPLEMENTER)) is not None:
            return t
        n = self._bump("impl")
        scope = h["contract"]["scope_paths"][0]
        rel = self.change_path or (scope if "." in scope.rsplit("/", 1)[-1] else f"{scope}/devwf_change.txt")
        workdir = h.get("workdir")
        if workdir:
            target = Path(workdir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(f"{h['task_id']} change {n}\n")
            run_git(["add", rel], workdir)
            run_git(["commit", "-q", "-m", f"devwf {h['task_id']} change {n}"], workdir)
            head = run_git(["rev-parse", "HEAD"], workdir)
        else:
            head = f"{n:040x}"
        boundary = {"adds_order_path": False, "activates_demo": False, "activates_live": False,
                    "touches_legacy": False, "replaces_baseline": False, "weakens_research_rule": False}
        boundary.update(self.boundary_overrides)
        payload = {"head_sha": head, "files_changed": [rel], "summary": f"change {n}", "boundary": boundary,
                   "baseline_retained": True}
        payload.update(self.implementation_overrides)
        return _packet(h, "implementation", payload)

    def qa(self, h: Mapping[str, Any]) -> Any:
        if (t := self._transient(QA)) is not None:
            return t
        verify = h["expected_kind"] == "verify_report"
        failing = not verify and self._bump("qa") <= self.qa_fail_times
        checks = {c: not failing for c in h["required_checks"] if c not in self.omit_checks}
        checks.update(self.extra_checks)
        payload = {"head_sha": h["expected_head"], "verdict": "FAIL" if failing else "PASS",
                   "tests": [{"name": "unit", "command": "python3 -m unittest", "passed": 10,
                              "failed": 1 if failing else 0}],
                   "checks": checks, "evidence_flags": list(self.qa_flags)}
        return _packet(h, h["expected_kind"], payload)

    def reviewer(self, h: Mapping[str, Any]) -> Any:
        if (t := self._transient(REVIEWER)) is not None:
            return t
        rejecting = self._bump("review") <= self.review_reject_times
        payload = {"head_sha": h["expected_head"], "verdict": "REQUEST_CHANGES" if rejecting else "APPROVE",
                   "findings": [{"severity": "major", "summary": "synthetic finding"}] if rejecting else [],
                   "promotion_claim": False, "evidence_flags": list(self.review_flags)}
        payload.update(self.review_overrides)
        return _packet(h, "review", payload)


def fake_bindings(script: Script) -> dict[str, FakeExecutor]:
    return {
        PLANNER: FakeExecutor("synthetic-a", "planner-sim", script.planner, usage=script.usage),
        IMPLEMENTER: FakeExecutor("synthetic-b", "implementer-sim", script.implementer, usage=script.usage),
        QA: FakeExecutor("synthetic-c", "qa-sim", script.qa, usage=script.usage),
        REVIEWER: FakeExecutor("synthetic-d", "reviewer-sim", script.reviewer, usage=script.usage),
    }
