"""Atlas overlay qualification: A1, B1-B6, C1-C3 plus legacy and execution-boundary gates."""
import sqlite3
import unittest

from devwf_harness import Harness

from tools.atlas_dev_workflow import policy
from tools.atlas_dev_workflow import simulation as sim
from tools.atlas_dev_workflow.contracts import TaskContract
from tools.atlas_dev_workflow.errors import PolicyViolation
from tools.atlas_dev_workflow.supervisor import decide, resume


def _final_evidence(h, task_id):
    return [e for e in h.events(task_id, "transition") if e["to_state"] == "DONE"][0]["payload"]["evidence"]


def _intake_policy(h, task_id):
    return h.events(task_id, "policy_evaluated")[0]["payload"]


class A1OrdinaryRefactor(unittest.TestCase):
    def test_refactor_needs_no_experiment_or_owner_approval(self):
        h = Harness(self)
        h.sup.intake(h.contract("a1-refactor", scope_paths=["atlas2/core/units.py"], impact_areas=["refactor"]))
        p = _intake_policy(h, "a1-refactor")
        self.assertEqual(p["classification"]["task_class"], "A")
        self.assertFalse(p["experiment_required"])
        self.assertEqual(p["required_checks"], ["unit_tests"])
        self.assertEqual(p["approval_categories"], [])
        h.sup.run("a1-refactor")
        self.assertEqual(h.store.get_task("a1-refactor")["state"], "DONE")
        self.assertEqual(h.store.approvals(task_id="a1-refactor"), [])

    def test_declared_class_is_a_floor_and_paths_escalate(self):
        h = Harness(self)
        t = h.sup.intake(h.contract("a1-escalate", scope_paths=["atlas2/evaluate/gates"], impact_areas=["refactor"]))
        self.assertEqual(t["task_class"], "B")

    def test_semantics_change_in_class_a_plan_blocks(self):
        h = Harness(self, sim.Script(plan_overrides={"semantics_change": True}))
        h.sup.intake(h.contract("a1-sneaky"))
        h.sup.run("a1-sneaky")
        self.assertEqual(h.store.get_task("a1-sneaky")["block_code"], "SEMANTICS_CHANGE_IN_CLASS_A")


B1_AREAS = ["H4_last_impulse_semantics", "holdout_evaluator_rules"]


def _b1(h, task_id, **overrides):
    data = dict(declared_class="B", impact_areas=B1_AREAS, scope_paths=["atlas2/evaluate"],
                experiment=sim.experiment(confirmatory=True, baseline="H4 baseline evaluator v1 (owner human H4 authority)",
                                          challenger="H4 evaluator challenger v2"),
                holdout_access={"requested": True, "via_preregistered_path": True, "grant_id": "grant-001",
                                "instrument_intervals": ["EURUSD:2024-01-01/2024-06-30"]})
    data.update(overrides)
    return h.contract(task_id, **data)


class B1H4EvaluatorChallenger(unittest.TestCase):
    def test_challenger_without_experiment_is_blocked_before_any_agent(self):
        h = Harness(self)
        t = h.sup.intake(_b1(h, "b1-noexp", experiment=None, holdout_access=None))
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "EXPERIMENT_REQUIRED"))
        self.assertEqual(h.agent_calls(), 0)

    def test_challenger_with_prereg_and_holdout_grant_keeps_baseline_and_needs_owner(self):
        h = Harness(self)
        h.sup.intake(_b1(h, "b1-ok"))
        p = _intake_policy(h, "b1-ok")
        self.assertTrue(p["experiment_required"])
        for check in ("holdout_guard", "baseline_retained", "causal_no_lookahead", "human_h4_authority_preserved"):
            self.assertIn(check, p["required_checks"])
        r = h.sup.run("b1-ok")
        self.assertTrue(r.waiting)
        approval = h.store.approvals(task_id="b1-ok")[0]
        self.assertIn("H4_last_impulse_semantics", approval["categories_json"])
        self.assertEqual(approval["activation_allowed"], 0)
        h.approve_pending("b1-ok")
        h.sup.run("b1-ok")
        self.assertEqual(h.store.get_task("b1-ok")["state"], "DONE")
        self.assertFalse(_final_evidence(h, "b1-ok")["boundary"]["strategy_promoted"])

    def test_baseline_replacement_is_blocked(self):
        h = Harness(self, sim.Script(boundary_overrides={"replaces_baseline": True}))
        h.sup.intake(_b1(h, "b1-overwrite"))
        h.sup.run("b1-overwrite")
        self.assertEqual(h.store.get_task("b1-overwrite")["block_code"], "BASELINE_OVERWRITTEN")

    def test_plan_without_retained_baseline_is_blocked(self):
        h = Harness(self, sim.Script(plan_overrides={"baseline_retained": False}))
        h.sup.intake(_b1(h, "b1-noplanbase"))
        h.sup.run("b1-noplanbase")
        self.assertEqual(h.store.get_task("b1-noplanbase")["block_code"], "BASELINE_NOT_RETAINED")

    def test_identical_baseline_and_challenger_rejected(self):
        h = Harness(self)
        t = h.sup.intake(_b1(h, "b1-same", experiment=sim.experiment(baseline="x", challenger="x")))
        self.assertIn("BASELINE_CHALLENGER_IDENTICAL", t["block_reason"])


class B2BreakEvenManagementExperiment(unittest.TestCase):
    def _contract(self, h, task_id):
        return h.contract(task_id, declared_class="B", impact_areas=["entry_stop_target_management"],
                          scope_paths=["atlas2/evaluate/arms"],
                          experiment=sim.experiment(experiment_id="EXP-BE-1R4",
                                                    baseline="2R target, no break-even (baseline arm)",
                                                    challenger="2R target, break-even at +1.4R (under validation)"))

    def test_paired_baseline_challenger_without_promotion(self):
        h = Harness(self)
        h.sup.intake(self._contract(h, "b2-be"))
        checks = _intake_policy(h, "b2-be")["required_checks"]
        for check in ("paired_baseline_challenger", "baseline_retained", "cost_realism"):
            self.assertIn(check, checks)
        h.sup.run("b2-be")
        h.approve_pending("b2-be")
        h.sup.run("b2-be")
        self.assertEqual(h.store.get_task("b2-be")["state"], "DONE")
        boundary = _final_evidence(h, "b2-be")["boundary"]
        self.assertEqual((boundary["strategy_promoted"], boundary["activation_allowed"]), (False, False))

    def test_reviewer_promotion_claim_is_invalid_output(self):
        h = Harness(self, sim.Script(review_overrides={"promotion_claim": True}))
        h.sup.intake(self._contract(h, "b2-promote"))
        h.sup.run("b2-promote")
        t = h.store.get_task("b2-promote")
        self.assertEqual((t["state"], t["block_code"]), ("FAILED", "INVALID_AGENT_OUTPUT"))

    def test_missing_paired_check_is_not_pass(self):
        h = Harness(self, sim.Script(omit_checks=("paired_baseline_challenger",)))
        h.sup.intake(self._contract(h, "b2-unpaired"))
        h.sup.run("b2-unpaired")
        t = h.store.get_task("b2-unpaired")
        self.assertEqual(t["block_code"], "FIX_CYCLES_EXHAUSTED")
        notes = [e["payload"]["evidence"].get("notes") for e in h.events("b2-unpaired", "transition")
                 if e["to_state"] == "FIXING"]
        self.assertIn("insufficient evidence reported as PASS; treated as FAIL", notes[0])


class B3MacroAvailability(unittest.TestCase):
    def _contract(self, h, task_id):
        return h.contract(task_id, declared_class="B", impact_areas=["macro_availability", "taint_causality"],
                          scope_paths=["atlas2/data"])

    def test_pit_and_non_pit_taint_checks_required(self):
        h = Harness(self)
        h.sup.intake(self._contract(h, "b3-macro"))
        checks = _intake_policy(h, "b3-macro")["required_checks"]
        for check in ("pit_availability", "non_pit_taint", "taint_propagation", "causal_no_lookahead"):
            self.assertIn(check, checks)
        h.sup.run("b3-macro")
        h.approve_pending("b3-macro")  # taint_causality is owner-sensitive
        h.sup.run("b3-macro")
        self.assertEqual(h.store.get_task("b3-macro")["state"], "DONE")

    def test_revised_macro_values_flag_blocks(self):
        h = Harness(self, sim.Script(qa_flags=("lookahead_or_revised_unavailable_data",)))
        h.sup.intake(self._contract(h, "b3-revised"))
        h.sup.run("b3-revised")
        t = h.store.get_task("b3-revised")
        self.assertEqual(t["block_code"], "EVIDENCE_BLOCKER")
        self.assertIn("lookahead_or_revised_unavailable_data", t["block_reason"])


class B4DetectorChange(unittest.TestCase):
    def _contract(self, h, task_id):
        return h.contract(task_id, declared_class="B", impact_areas=["detector_capture"], scope_paths=["atlas2/detect"])

    def test_capture_before_gates_and_rejections_retained(self):
        h = Harness(self)
        h.sup.intake(self._contract(h, "b4-detector"))
        checks = _intake_policy(h, "b4-detector")["required_checks"]
        self.assertIn("candidate_capture_before_gates", checks)
        self.assertIn("rejected_candidates_retained", checks)
        h.sup.run("b4-detector")
        self.assertEqual(h.store.get_task("b4-detector")["state"], "DONE")

    def test_missing_rejected_candidate_evidence_blocks(self):
        h = Harness(self, sim.Script(qa_flags=("rejected_candidate_evidence_missing",)))
        h.sup.intake(self._contract(h, "b4-norejects"))
        h.sup.run("b4-norejects")
        self.assertEqual(h.store.get_task("b4-norejects")["block_code"], "EVIDENCE_BLOCKER")


class B5HoldoutMisuse(unittest.TestCase):
    def test_holdout_access_outside_prereg_denied_and_journaled(self):
        h = Harness(self)
        t = h.sup.intake(_b1(h, "b5-peek", holdout_access={"requested": True, "via_preregistered_path": False}))
        self.assertEqual(t["state"], "BLOCKED")
        self.assertIn("HOLDOUT_ACCESS_DENIED", t["block_reason"])
        blocks = _intake_policy(h, "b5-peek")["blocks"]
        self.assertIn("HOLDOUT_ACCESS_DENIED", [b["code"] for b in blocks])
        self.assertEqual(h.agent_calls(), 0)
        with self.assertRaises(PolicyViolation):
            resume(h.store, "b5-peek", actor="operator")

    def test_holdout_exposure_flag_during_review_blocks(self):
        h = Harness(self, sim.Script(review_flags=("holdout_exposed_outside_prereg",)))
        h.sup.intake(_b1(h, "b5-exposed"))
        h.sup.run("b5-exposed")
        self.assertEqual(h.store.get_task("b5-exposed")["block_code"], "EVIDENCE_BLOCKER")


class B6PostHocEvaluatorTuning(unittest.TestCase):
    def test_posthoc_tuning_invalidates_confirmatory_status(self):
        h = Harness(self)
        exp = sim.experiment(confirmatory=True, protected_results_observed=True,
                             evaluator_changed_after_protected_results=True)
        t = h.sup.intake(_b1(h, "b6-tuned", experiment=exp))
        self.assertEqual(t["block_code"], "CONFIRMATORY_INVALID_NEW_EXPERIMENT_REQUIRED")
        with self.assertRaises(PolicyViolation):
            resume(h.store, "b6-tuned", actor="operator")
        fresh = h.sup.intake(_b1(h, "b6-new-exp", experiment=sim.experiment(experiment_id="EXP-SIM-002",
                                                                              confirmatory=True)))
        self.assertEqual(fresh["state"], "NEW_TASK")

    def test_unfrozen_evaluator_before_protected_exposure_blocked(self):
        h = Harness(self)
        t = h.sup.intake(_b1(h, "b6-unfrozen", experiment=sim.experiment(evaluator_frozen=False)))
        self.assertIn("EVALUATOR_NOT_FROZEN", t["block_reason"])

    def test_posthoc_flag_from_qa_blocks(self):
        h = Harness(self, sim.Script(qa_flags=("evaluator_edited_after_protected_results",)))
        h.sup.intake(_b1(h, "b6-qaflag"))
        h.sup.run("b6-qaflag")
        self.assertEqual(h.store.get_task("b6-qaflag")["block_code"], "EVIDENCE_BLOCKER")


class C1RiskGovernorChange(unittest.TestCase):
    def test_owner_approval_required_and_no_activation(self):
        h = Harness(self)
        h.sup.intake(h.contract("c1-risk", declared_class="C", impact_areas=["risk_sizing"],
                                scope_paths=["atlas2/risk_governor"]))
        p = _intake_policy(h, "c1-risk")
        self.assertEqual(p["classification"]["task_class"], "C")
        for check in ("no_order_path", "no_live_activation", "fail_closed_default"):
            self.assertIn(check, p["required_checks"])
        self.assertTrue(h.sup.run("c1-risk").waiting)
        approval = h.store.approvals(task_id="c1-risk", status="PENDING")[0]
        self.assertIn("class_C", approval["categories_json"])
        with self.assertRaises(PolicyViolation):
            decide(h.store, approval["approval_id"], approve=True, actor="owner", activation_allowed=True)
        self.assertEqual(len(h.events("c1-risk", "activation_request_rejected")), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            h.store.conn.execute("UPDATE approvals SET activation_allowed=1")
        h.approve_pending("c1-risk")
        h.sup.run("c1-risk")
        self.assertEqual(h.store.get_task("c1-risk")["state"], "DONE")
        self.assertEqual(_final_evidence(h, "c1-risk")["boundary"]["activation_allowed"], False)

    def test_owner_rejection_blocks(self):
        h = Harness(self)
        h.sup.intake(h.contract("c1-reject", declared_class="C", impact_areas=["risk_sizing"],
                                scope_paths=["atlas2/risk_governor"]))
        h.sup.run("c1-reject")
        a = h.store.approvals(task_id="c1-reject")[0]
        decide(h.store, a["approval_id"], approve=False, actor="owner", note="not now")
        h.sup.run("c1-reject")
        self.assertEqual(h.store.get_task("c1-reject")["block_code"], "OWNER_REJECTED")


class C2DemoExecutionCodePatch(unittest.TestCase):
    def _contract(self, h, task_id, **kw):
        data = dict(declared_class="C", impact_areas=["execution_transport"], scope_paths=["bridges/demo_execution"],
                    execution_stage="demo_code")
        data.update(kw)
        return h.contract(task_id, **data)

    def test_demo_code_patch_is_fail_closed_and_merge_is_not_activation(self):
        h = Harness(self, sim.Script(boundary_overrides={"adds_order_path": True}))
        h.sup.intake(self._contract(h, "c2-demo"))
        checks = _intake_policy(h, "c2-demo")["required_checks"]
        for check in ("fail_closed_default", "no_real_money_path", "no_live_activation"):
            self.assertIn(check, checks)
        h.sup.run("c2-demo")
        h.approve_pending("c2-demo")
        h.sup.run("c2-demo")
        self.assertEqual(h.store.get_task("c2-demo")["state"], "DONE")
        boundary = _final_evidence(h, "c2-demo")["boundary"]
        self.assertEqual((boundary["demo_activation"], boundary["real_money"], boundary["merge_is_activation"]),
                         ("NOT_ALLOWED", "NOT_ALLOWED", False))
        merge = [e for e in h.events("c2-demo", "transition") if e["to_state"] == "VERIFY"][0]
        self.assertEqual(merge["payload"]["evidence"]["activation"], "NOT_ACTIVATED")

    def test_order_path_outside_demo_code_task_blocked(self):
        h = Harness(self, sim.Script(boundary_overrides={"adds_order_path": True}))
        h.sup.intake(self._contract(h, "c2-sneak", execution_stage="none"))
        h.sup.run("c2-sneak")
        self.assertEqual(h.store.get_task("c2-sneak")["block_code"], "EXECUTION_BOUNDARY_EXPANSION")

    def test_implementer_activation_attempt_blocked(self):
        h = Harness(self, sim.Script(boundary_overrides={"activates_demo": True}))
        h.sup.intake(self._contract(h, "c2-activate"))
        h.sup.run("c2-activate")
        self.assertEqual(h.store.get_task("c2-activate")["block_code"], "ACTIVATION_FORBIDDEN")

    def test_activation_allowed_true_rejected_at_intake(self):
        h = Harness(self)
        t = h.sup.intake(self._contract(h, "c2-flag", activation_allowed=True))
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "ACTIVATION_FORBIDDEN"))
        self.assertEqual(h.agent_calls(), 0)


class C3LimitedLiveRequest(unittest.TestCase):
    def test_limited_live_is_blocked_and_routed_not_executed(self):
        for stage in ("limited_live", "real_money", "demo_activation"):
            h = Harness(self)
            t = h.sup.intake(h.contract(f"c3-{stage.replace('_', '-')}", declared_class="C",
                                        impact_areas=["production_live"], scope_paths=["bridges/live"],
                                        execution_stage=stage))
            self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "SEPARATE_OWNER_AUTHORIZATION_REQUIRED"))
            self.assertFalse(h.sup.run(t["task_id"]).progressed)
            self.assertEqual(h.agent_calls(), 0)
            self.assertEqual(h.store.mutations(t["task_id"]), [])
            self.assertIsNone(h.store.get_task(t["task_id"])["worktree_path"])
            with self.assertRaises(PolicyViolation):
                resume(h.store, t["task_id"], actor="operator")


class LegacyBoundary(unittest.TestCase):
    def test_legacy_mutation_without_authorization_blocked(self):
        h = Harness(self)
        t = h.sup.intake(h.contract("legacy-x", declared_class="C", scope_paths=["atlas/execution"]))
        self.assertEqual(t["block_code"], "LEGACY_MUTATION_UNAUTHORIZED")

    def test_authorized_legacy_mutation_forces_class_c_and_owner_gate(self):
        h = Harness(self)
        t = h.sup.intake(h.contract("legacy-ok", declared_class="A", scope_paths=["atlas/reporting"],
                                    legacy_mutation_authorized=True))
        self.assertEqual(t["task_class"], "C")
        h.sup.run("legacy-ok")
        approval = h.store.approvals(task_id="legacy-ok", status="PENDING")[0]
        self.assertIn("legacy_mutation", approval["categories_json"])

    def test_files_outside_scope_blocked(self):
        h = Harness(self, sim.Script(change_path="atlas/legacy_file.py"))
        h.sup.intake(h.contract("scope-escape"))
        h.sup.run("scope-escape")
        t = h.store.get_task("scope-escape")
        self.assertEqual(t["state"], "BLOCKED")
        self.assertIn("LEGACY_MUTATION_UNAUTHORIZED", t["block_reason"])
        self.assertIn("SCOPE_VIOLATION", t["block_reason"])


class PolicyUnits(unittest.TestCase):
    def test_no_universal_numeric_promotion_threshold_exists(self):
        import inspect
        source = inspect.getsource(policy)
        for token in ("sharpe", "min_trades", "win_rate", "profit_factor"):
            self.assertNotIn(token, source.lower())

    def test_classification_never_downgrades(self):
        c = TaskContract.from_dict(sim.contract("x-floor", "0" * 40, declared_class="C"))
        self.assertEqual(policy.classify(c).task_class, "C")


if __name__ == "__main__":
    unittest.main()
