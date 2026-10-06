"""Core qualification scenarios 1-12 for the reusable five-agent development workflow."""
import json
import sqlite3
import unittest
from pathlib import Path

from devwf_harness import HAPPY_PATH, HOUR_US, Harness

from tools.atlas_dev_workflow import simulation as sim
from tools.atlas_dev_workflow.errors import (ContractError, GitSafetyError, IllegalTransition, PolicyViolation,
                                             StaleLease, StateStoreError)
from tools.atlas_dev_workflow.gitops import FakeMergeGateway, ManualMergeGateway, WorktreeManager, guard_git_args
from tools.atlas_dev_workflow.states import State, legal_targets, validate_transition
from tools.atlas_dev_workflow.supervisor import cancel, pause, resume


class S01HappyPath(unittest.TestCase):
    def test_happy_engineering_path_reaches_done(self):
        h = Harness(self)
        h.sup.intake(h.contract("happy-path"))
        result = h.sup.run("happy-path")
        task = h.store.get_task("happy-path")
        self.assertEqual(task["state"], "DONE")
        self.assertEqual(h.transitions("happy-path"), HAPPY_PATH)
        self.assertEqual(task["fix_cycles"], 0)
        # exact head tracking: durable head == worktree head == approved head
        self.assertEqual(task["head_sha"], h.workspace.head(task["worktree_path"]))
        self.assertEqual(task["approved_head_sha"], task["head_sha"])
        self.assertNotEqual(task["head_sha"], h.base)
        self.assertFalse(Path(task["worktree_path"]).resolve().is_relative_to(h.repo.resolve()))
        self.assertEqual(h.workspace.current_branch(task["worktree_path"]), "devwf/happy-path")
        done = h.transitions("happy-path")[-1]
        self.assertEqual(done, ("VERIFY", "DONE"))
        final = [e for e in h.events("happy-path", "transition") if e["to_state"] == "DONE"][0]
        self.assertEqual(final["payload"]["evidence"]["boundary"]["strategy_promoted"], False)
        self.assertEqual(final["payload"]["evidence"]["boundary"]["merge_is_activation"], False)
        self.assertTrue(h.store.verify_journal()[0])
        self.assertFalse(result.waiting)


class S02TestFailureRecovery(unittest.TestCase):
    def test_qa_failure_goes_through_fixing_then_done(self):
        h = Harness(self, sim.Script(qa_fail_times=1))
        h.sup.intake(h.contract("qa-fix"))
        h.sup.run("qa-fix")
        t = h.store.get_task("qa-fix")
        self.assertEqual(t["state"], "DONE")
        self.assertEqual(t["fix_cycles"], 1)
        path = h.transitions("qa-fix")
        self.assertIn(("TESTING", "FIXING"), path)
        self.assertIn(("FIXING", "TESTING"), path)


class S03ReviewerRejectionRecovery(unittest.TestCase):
    def test_reviewer_request_changes_goes_through_fixing_then_done(self):
        h = Harness(self, sim.Script(review_reject_times=1))
        h.sup.intake(h.contract("review-fix"))
        h.sup.run("review-fix")
        t = h.store.get_task("review-fix")
        self.assertEqual(t["state"], "DONE")
        self.assertIn(("REVIEW", "FIXING"), h.transitions("review-fix"))
        self.assertEqual(t["fix_cycles"], 1)


class S04FixExhaustion(unittest.TestCase):
    def test_fix_budget_exhaustion_blocks(self):
        h = Harness(self, sim.Script(qa_fail_times=99))
        h.sup.intake(h.contract("fix-exhaust", max_fix_cycles=3))
        h.sup.run("fix-exhaust")
        t = h.store.get_task("fix-exhaust")
        self.assertEqual((t["state"], t["block_code"], t["fix_cycles"]), ("BLOCKED", "FIX_CYCLES_EXHAUSTED", 3))
        with self.assertRaises(PolicyViolation):
            resume(h.store, "fix-exhaust", actor="operator")

    def test_fix_cycle_bounds_default_3_max_5(self):
        h = Harness(self)
        self.assertEqual(h.sup.intake(h.contract("fix-default"))["max_fix_cycles"], 3)
        with self.assertRaises(ContractError):
            h.sup.intake(h.contract("fix-too-many", max_fix_cycles=6))


class S05RestartResume(unittest.TestCase):
    def test_crash_after_agent_output_resumes_without_reinvoking_agent(self):
        h = Harness(self)
        h.sup.intake(h.contract("restart"))
        while h.store.get_task("restart")["state"] != "TESTING":
            h.sup.step("restart")
        original = h.store.transition

        def crash(*args, **kwargs):
            raise RuntimeError("simulated process crash before commit")
        h.store.transition = crash
        with self.assertRaises(RuntimeError):
            h.sup.step("restart")  # QA packet recorded durably, transition never committed
        h.store.transition = original
        qa_calls_before = len(h.bindings["qa"].calls)
        self.assertEqual(h.store.get_task("restart")["state"], "TESTING")

        sup = h.restart()
        sup.run("restart")
        self.assertEqual(h.store.get_task("restart")["state"], "DONE")
        self.assertEqual(len(h.events("restart", "agent_replayed")), 1)
        # only the post-merge verify call is new; the recorded QA step was replayed, not re-invoked
        self.assertEqual(len(h.bindings["qa"].calls), qa_calls_before + 1)
        self.assertEqual(len(set(h.bindings["qa"].calls)), len(h.bindings["qa"].calls))

    def test_hard_crash_lease_expires_then_new_worker_resumes(self):
        h = Harness(self)
        h.sup.intake(h.contract("hard-crash"))
        h.sup.step("hard-crash")
        h.store.acquire_lease("hard-crash", "dead-worker", HOUR_US)  # crashed while holding the lease
        blocked = h.sup.step("hard-crash")
        self.assertFalse(blocked.progressed)
        self.assertIn("lease_unavailable", blocked.action)
        h.clock.advance(HOUR_US + 1)
        h.restart().run("hard-crash")
        self.assertEqual(h.store.get_task("hard-crash")["state"], "DONE")


class S06ReplayIdempotency(unittest.TestCase):
    def test_reintake_is_idempotent_and_conflicts_are_rejected(self):
        h = Harness(self)
        first = h.sup.intake(h.contract("idem"))
        again = h.sup.intake(h.contract("idem"))
        self.assertEqual(first["contract_digest"], again["contract_digest"])
        self.assertEqual(len(h.events("idem", "task_created")), 1)
        with self.assertRaises(StateStoreError):
            h.sup.intake(h.contract("idem", title="different contract, same id"))

    def test_journal_replay_matches_durable_state_and_is_tamper_evident(self):
        h = Harness(self, sim.Script(qa_fail_times=1))
        h.sup.intake(h.contract("replay"))
        h.sup.run("replay")
        t = h.store.get_task("replay")
        replayed = h.store.replay_state("replay")
        self.assertEqual((replayed["state"], replayed["version"], replayed["head_sha"], replayed["fix_cycles"]),
                         (t["state"], t["version"], t["head_sha"], t["fix_cycles"]))
        with self.assertRaises(sqlite3.DatabaseError):
            h.store.conn.execute("UPDATE journal SET actor='x' WHERE seq=1")
        with self.assertRaises(sqlite3.DatabaseError):
            h.store.conn.execute("DELETE FROM journal")
        h.store.conn.execute("DROP TRIGGER journal_no_update")
        h.store.conn.execute("UPDATE journal SET payload_json='{}' WHERE seq=2")
        ok, detail = h.store.verify_journal()
        self.assertFalse(ok)
        self.assertIn("seq 2", detail)

    def test_step_keys_are_deterministic(self):
        a, b = Harness(self), Harness(self)
        for h in (a, b):
            h.sup.intake(sim.contract("det", "0" * 40))
        ta, tb = a.store.get_task("det"), b.store.get_task("det")
        self.assertEqual(a.sup._step_key(ta, "planner", "plan"), b.sup._step_key(tb, "planner", "plan"))


class S07InvalidTransition(unittest.TestCase):
    def test_illegal_transitions_rejected(self):
        for src, dst in [("NEW_TASK", "DONE"), ("PLANNING", "MERGE"), ("TESTING", "APPROVAL"), ("DONE", "PLANNING"),
                         ("CANCELLED", "PLANNING"), ("FAILED", "FIXING"), ("REVIEW", "DONE"), ("APPROVAL", "DONE")]:
            with self.assertRaises(IllegalTransition, msg=f"{src}->{dst}"):
                validate_transition(src, dst)
        with self.assertRaises(IllegalTransition):
            validate_transition("PAUSED", "MERGE", origin="TESTING")
        with self.assertRaises(IllegalTransition):
            validate_transition("NEW_TASK", "NOT_A_STATE")
        for terminal in ("DONE", "FAILED", "CANCELLED"):
            self.assertEqual(legal_targets(State(terminal)), frozenset())

    def test_store_rejects_illegal_transition_and_keeps_state(self):
        h = Harness(self)
        h.sup.intake(h.contract("illegal"))
        with self.assertRaises(IllegalTransition):
            h.store.transition("illegal", State.DONE, actor="rogue", reason="skip", expected_version=0)
        self.assertEqual(h.store.get_task("illegal")["state"], "NEW_TASK")
        self.assertEqual(h.events("illegal", "transition"), [])


class S08PauseResumeCancel(unittest.TestCase):
    def test_pause_resume_returns_to_origin_then_completes(self):
        h = Harness(self)
        h.sup.intake(h.contract("pausable"))
        h.sup.step("pausable")
        h.sup.step("pausable")
        self.assertEqual(h.store.get_task("pausable")["state"], "READY")
        pause(h.store, "pausable", actor="operator", reason="owner hold")
        self.assertFalse(h.sup.step("pausable").progressed)
        self.assertEqual(h.store.get_task("pausable")["state"], "PAUSED")
        resume(h.store, "pausable", actor="operator")
        self.assertEqual(h.store.get_task("pausable")["state"], "READY")
        h.sup.run("pausable")
        self.assertEqual(h.store.get_task("pausable")["state"], "DONE")

    def test_cancel_is_terminal(self):
        h = Harness(self)
        h.sup.intake(h.contract("cancel-me"))
        h.sup.step("cancel-me")
        cancel(h.store, "cancel-me", actor="operator", reason="no longer needed")
        self.assertEqual(h.store.get_task("cancel-me")["state"], "CANCELLED")
        self.assertFalse(h.sup.run("cancel-me").progressed)
        with self.assertRaises(PolicyViolation):
            cancel(h.store, "cancel-me", actor="operator", reason="again")
        with self.assertRaises(PolicyViolation):
            resume(h.store, "cancel-me", actor="operator")


class S09StaleWorkerLease(unittest.TestCase):
    def test_operator_action_fences_out_inflight_worker(self):
        h = Harness(self)
        h.sup.intake(h.contract("fenced"))
        token = h.store.acquire_lease("fenced", "worker-a", HOUR_US)
        pause(h.store, "fenced", actor="operator", reason="hold")  # bumps fencing token
        with self.assertRaises(StaleLease):
            h.store.transition("fenced", State.PLANNING, actor="worker-a", reason="late", expected_version=0,
                               lease=("worker-a", token))

    def test_worker_paused_mid_agent_call_cannot_commit_packet(self):
        h = Harness(self)
        h.sup.intake(h.contract("mid-call"))
        h.sup.step("mid-call")  # -> PLANNING
        real = h.bindings["planner"].responder

        def pausing_planner(handoff):
            pause(h.store, "mid-call", actor="operator", reason="pause during agent call")
            return real(handoff)
        h.bindings["planner"].responder = pausing_planner
        result = h.sup.step("mid-call")
        self.assertEqual(result.action, "stale_lease_rejected")
        self.assertEqual(h.store.get_task("mid-call")["state"], "PAUSED")
        self.assertEqual(h.store.agent_runs("mid-call"), [])
        self.assertEqual(len(h.events("mid-call", "stale_worker_rejected")), 1)

    def test_expired_lease_holder_cannot_commit_after_takeover(self):
        h = Harness(self)
        h.sup.intake(h.contract("takeover"))
        old = h.store.acquire_lease("takeover", "worker-old", 10)
        h.clock.advance(11)
        h.store.acquire_lease("takeover", "worker-new", HOUR_US)
        with self.assertRaises(StaleLease):
            h.store.transition("takeover", State.PLANNING, actor="worker-old", reason="late", expected_version=0,
                               lease=("worker-old", old))
        with self.assertRaises(StaleLease):
            h.store.acquire_lease("takeover", "worker-third", HOUR_US)


class S10DuplicateExternalMutation(unittest.TestCase):
    def test_merge_request_sent_once_across_repeated_steps(self):
        gateway = FakeMergeGateway(defer=True)
        h = Harness(self, gateway=gateway)
        h.sup.intake(h.contract("merge-once"))
        r = h.sup.run("merge-once")
        self.assertTrue(r.waiting)
        self.assertEqual(h.store.get_task("merge-once")["state"], "MERGE")
        for _ in range(3):
            h.sup.step("merge-once")
        h.restart().run("merge-once")
        self.assertEqual(h.store.get_task("merge-once")["state"], "DONE")
        self.assertEqual(gateway.request_count, 1)

    def test_crash_after_intent_before_request_does_not_duplicate(self):
        gateway = FakeMergeGateway()
        h = Harness(self, gateway=gateway)
        h.sup.intake(h.contract("merge-crash"))
        while h.store.get_task("merge-crash")["state"] != "MERGE":
            h.sup.step("merge-crash")
        real = gateway.request_merge
        gateway.request_merge = lambda **kw: (_ for _ in ()).throw(RuntimeError("crash before send"))
        with self.assertRaises(RuntimeError):
            h.sup.step("merge-crash")
        gateway.request_merge = real
        h.restart().run("merge-crash")
        self.assertEqual(h.store.get_task("merge-crash")["state"], "DONE")
        self.assertEqual(gateway.request_count, 1)
        self.assertEqual([m["status"] for m in h.store.mutations("merge-crash") if m["kind"] == "merge_request"], ["DONE"])

    def test_idempotency_key_reuse_with_different_request_is_refused(self):
        h = Harness(self)
        h.sup.intake(h.contract("key-reuse"))
        h.store.begin_mutation("k1", task_id="key-reuse", kind="x", request={"a": 1}, actor="t")
        self.assertFalse(h.store.begin_mutation("k1", task_id="key-reuse", kind="x", request={"a": 1}, actor="t")["created"])
        with self.assertRaises(StateStoreError):
            h.store.begin_mutation("k1", task_id="key-reuse", kind="x", request={"a": 2}, actor="t")


class S11UnsafeGitRejected(unittest.TestCase):
    def test_direct_main_branch_task_blocked_at_intake(self):
        h = Harness(self)
        t = h.sup.intake(h.contract("main-direct", branch="main"))
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "DIRECT_MAIN_FORBIDDEN"))
        self.assertEqual(h.agent_calls(), 0)

    def test_unsafe_git_commands_refused(self):
        for args in (["push", "--force", "origin", "x"], ["push", "-f"], ["push", "origin", "HEAD:main"],
                     ["push", "origin", "+x:x"], ["push", "origin", "refs/heads/master"], ["reset", "--hard"],
                     ["clean", "-fdx"], ["branch", "-D", "x"], ["stash"], ["rebase", "main"],
                     ["worktree", "remove", "--force", "p"], ["checkout", "-f", "x"]):
            with self.assertRaises(GitSafetyError, msg=args):
                guard_git_args(args)
        guard_git_args(["push", "origin", "devwf/task"])  # ordinary task-branch push is allowed

    def test_worktree_manager_refuses_protected_branch_and_inside_repo_root(self):
        h = Harness(self)
        with self.assertRaises(GitSafetyError):
            h.workspace.create("t-main", "main", h.base)
        with self.assertRaises(GitSafetyError):
            h.workspace.create("t-short", "devwf/t-short", h.base[:12])
        with self.assertRaises(GitSafetyError):
            WorktreeManager(h.repo, h.repo / "nested-worktrees")
        with self.assertRaises(GitSafetyError):
            ManualMergeGateway(h.tmp / "mr").request_merge(key="k", task_id="t", branch="main", target="main",
                                                           head_sha=h.base)


class S12DirtyTargetPreserved(unittest.TestCase):
    def test_unknown_existing_target_is_refused_and_untouched(self):
        h = Harness(self)
        target = h.workspace.path_for("dirty-target")
        target.mkdir(parents=True)
        (target / "operator_notes.txt").write_text("unsaved work", encoding="utf-8")
        h.sup.intake(h.contract("dirty-target"))
        h.sup.run("dirty-target")
        t = h.store.get_task("dirty-target")
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "GIT_UNSAFE_TARGET"))
        self.assertEqual((target / "operator_notes.txt").read_text(encoding="utf-8"), "unsaved work")

    def test_dirty_registered_worktree_is_refused_and_preserved(self):
        h = Harness(self)
        info = h.workspace.create("dirty-wt", "devwf/dirty-wt", h.base)
        scratch = Path(info["path"]) / "wip.txt"
        scratch.write_text("uncommitted", encoding="utf-8")
        with self.assertRaises(GitSafetyError):
            h.workspace.create("dirty-wt", "devwf/dirty-wt", h.base)
        self.assertEqual(scratch.read_text(encoding="utf-8"), "uncommitted")
        self.assertTrue(h.workspace.is_dirty(info["path"]))

    def test_uncommitted_implementation_is_blocked(self):
        h = Harness(self)
        real = h.bindings["implementer"].responder

        def sloppy(handoff):
            packet = real(handoff)
            (Path(handoff["workdir"]) / "atlas2/core/leftover.txt").write_text("x", encoding="utf-8")
            return packet
        h.bindings["implementer"].responder = sloppy
        h.sup.intake(h.contract("sloppy"))
        h.sup.run("sloppy")
        self.assertEqual(h.store.get_task("sloppy")["block_code"], "UNCOMMITTED_CHANGES")


class ProviderRetryAndOutputValidation(unittest.TestCase):
    def test_transient_provider_errors_retried_within_bound(self):
        h = Harness(self, sim.Script(provider_errors={"planner": 2}))
        h.sup.intake(h.contract("retry-ok"))
        h.sup.run("retry-ok")
        self.assertEqual(h.store.get_task("retry-ok")["state"], "DONE")
        self.assertEqual(len(h.events("retry-ok", "agent_attempt_failed")), 2)

    def test_provider_exhaustion_blocks_recoverably_and_resumes(self):
        h = Harness(self, sim.Script(provider_errors={"planner": 3}))
        h.sup.intake(h.contract("retry-out"))
        h.sup.run("retry-out")
        t = h.store.get_task("retry-out")
        self.assertEqual((t["state"], t["block_code"], t["origin_state"]), ("BLOCKED", "PROVIDER_UNAVAILABLE", "PLANNING"))
        resume(h.store, "retry-out", actor="operator")
        h.sup.run("retry-out")
        self.assertEqual(h.store.get_task("retry-out")["state"], "DONE")

    def test_invalid_structured_output_fails_after_retries(self):
        h = Harness(self, sim.Script(invalid_output={"qa": 3}))
        h.sup.intake(h.contract("bad-json"))
        h.sup.run("bad-json")
        t = h.store.get_task("bad-json")
        self.assertEqual((t["state"], t["block_code"]), ("FAILED", "INVALID_AGENT_OUTPUT"))

    def test_head_mismatch_reported_by_implementer_blocks(self):
        h = Harness(self, sim.Script(implementation_overrides={"head_sha": "f" * 40}))
        h.sup.intake(h.contract("head-lie"))
        h.sup.run("head-lie")
        self.assertEqual(h.store.get_task("head-lie")["block_code"], "HEAD_MISMATCH")

    def test_reviewer_must_be_independent_from_implementer(self):
        h = Harness(self)
        same = dict(h.bindings, reviewer=h.bindings["implementer"])
        from tools.atlas_dev_workflow.supervisor import Supervisor
        with self.assertRaises(ContractError):
            Supervisor(h.store, same)
        with self.assertRaises(ContractError):
            Supervisor(h.store, {k: v for k, v in h.bindings.items() if k != "qa"})


if __name__ == "__main__":
    unittest.main()
