"""Shared qualification harness: synthetic agents, scratch Git repo, injectable clock. No model/broker calls."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools.atlas_dev_workflow import simulation as sim
from tools.atlas_dev_workflow.gitops import FakeMergeGateway, WorktreeManager
from tools.atlas_dev_workflow.store import Store
from tools.atlas_dev_workflow.supervisor import Supervisor
from tools.owner_dev_policy.policy import OwnerDevelopmentPolicy

HOUR_US = 3600 * 1_000_000


class FakeClock:
    def __init__(self, start: int = 1_790_000_000_000_000):
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, us: int) -> None:
        self.now += us


class Harness:
    def __init__(self, case: unittest.TestCase, script: sim.Script | None = None, *, gateway=None,
                 worker_id: str = "worker-1", max_provider_retries: int = 2, lease_ttl_us: int = HOUR_US):
        self.tmp = Path(tempfile.mkdtemp(prefix="devwf-test-"))
        case.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.base = sim.make_repo(self.tmp)
        self.clock = FakeClock()
        self.db_path = self.tmp / "state" / "state.sqlite3"
        self.script = script or sim.Script()
        self.bindings = sim.fake_bindings(self.script)
        self.gateway = gateway or FakeMergeGateway()
        self.workspace = WorktreeManager(self.repo, self.tmp / "worktrees")
        self.worker_id = worker_id
        self.max_provider_retries = max_provider_retries
        self.lease_ttl_us = lease_ttl_us
        self.store = Store(self.db_path, clock=self.clock)
        case.addCleanup(lambda: self.store.close())
        self.sup = self.supervisor()

    def supervisor(self, worker_id: str | None = None) -> Supervisor:
        return Supervisor(self.store, self.bindings, workspace=self.workspace, merge_gateway=self.gateway,
                          worker_id=worker_id or self.worker_id, lease_ttl_us=self.lease_ttl_us,
                          owner_policy=OwnerDevelopmentPolicy(max_provider_retries=self.max_provider_retries))

    def restart(self) -> Supervisor:
        """Simulate a process restart: brand-new Store connection and Supervisor on the same durable DB."""
        self.store.close()
        self.store = Store(self.db_path, clock=self.clock)
        self.sup = self.supervisor()
        return self.sup

    def contract(self, task_id: str, **overrides):
        return sim.contract(task_id, self.base, **overrides)

    def transitions(self, task_id: str) -> list[tuple[str, str]]:
        return [(e["from_state"], e["to_state"]) for e in self.store.journal_entries(task_id)
                if e["event_type"] == "transition"]

    def events(self, task_id: str, event_type: str) -> list[dict]:
        return [e for e in self.store.journal_entries(task_id) if e["event_type"] == event_type]

    def agent_calls(self) -> int:
        return sum(len(e.calls) for e in self.bindings.values())

    def approve_pending(self, task_id: str, *, by: str = "owner"):
        from tools.atlas_dev_workflow.supervisor import decide
        pending = self.store.approvals(task_id=task_id, status="PENDING")
        assert len(pending) == 1, pending
        return decide(self.store, pending[0]["approval_id"], approve=True, actor=by, note="owner reviewed")


HAPPY_PATH = [
    ("NEW_TASK", "PLANNING"), ("PLANNING", "READY"), ("READY", "IMPLEMENTING"), ("IMPLEMENTING", "TESTING"),
    ("TESTING", "REVIEW"), ("REVIEW", "APPROVAL"), ("APPROVAL", "MERGE"), ("MERGE", "VERIFY"), ("VERIFY", "DONE"),
]
