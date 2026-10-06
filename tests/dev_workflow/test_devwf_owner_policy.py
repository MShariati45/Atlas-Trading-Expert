"""Owner Development Policy qualification: identity boundary, monitoring/event contracts, priority, provider
failover, reviewer independence, context/usage telemetry, findings, DoD composition and control requests."""
import ast
import json
import re
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from devwf_harness import HOUR_US, Harness

from tools.atlas_dev_workflow import project, projections
from tools.atlas_dev_workflow import simulation as sim
from tools.atlas_dev_workflow.contracts import HANDOFF_V1, TaskContract, digest
from tools.atlas_dev_workflow.errors import ContractError, PolicyViolation, ProviderExhausted
from tools.atlas_dev_workflow.executors import CliExecutor, ExecResult, FakeExecutor
from tools.atlas_dev_workflow.policy import approval_categories, classify, required_checks
from tools.atlas_dev_workflow.supervisor import Supervisor, apply_control
from tools.owner_dev_policy import checkpoint as owner_checkpoint
from tools.owner_dev_policy import classification, compute, done, events, glossary, monitoring, providers
from tools.owner_dev_policy.policy import OwnerDevelopmentPolicy
from tools.owner_dev_policy.schema import SchemaError

ROOT = Path(__file__).resolve().parents[2]
OWNER_PKG = ROOT / "tools" / "owner_dev_policy"
ATLAS_PKG = ROOT / "tools" / "atlas_dev_workflow"
B1_AREAS = ["H4_last_impulse_semantics", "holdout_evaluator_rules"]


def _imports(root: Path):
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path, alias.name, 0
            elif isinstance(node, ast.ImportFrom):
                yield path, node.module or "", node.level


def _b1(h, task_id, **overrides):
    data = dict(declared_class="B", impact_areas=B1_AREAS, scope_paths=[f"atlas2/evaluate/{task_id}"],
                experiment=sim.experiment(confirmatory=True), holdout_access={
                    "requested": True, "via_preregistered_path": True, "grant_id": "grant-001",
                    "instrument_intervals": ["EURUSD:2024-01-01/2024-06-30"]})
    data.update(overrides)
    return h.contract(task_id, **data)


def _chain_harness(case, implementers, reviewers, script=None, policy=None):
    """Harness whose implementer/reviewer roles are failover chains of FakeExecutors."""
    h = Harness(case, script)
    bindings = dict(h.bindings, implementer=implementers, reviewer=reviewers)
    h.bindings = bindings
    h.sup = Supervisor(h.store, bindings, workspace=h.workspace, merge_gateway=h.gateway, worker_id=h.worker_id,
                       lease_ttl_us=h.lease_ttl_us, owner_policy=policy or OwnerDevelopmentPolicy())
    return h


def _exhausting(responder, times=1):
    """Wrap a responder so the first `times` calls fail with provider usage exhaustion."""
    state = {"n": 0}

    def run(handoff):
        state["n"] += 1
        if state["n"] <= times:
            return ProviderExhausted("usage limit reached for this billing period")
        return responder(handoff)
    return run


# 1 -- identity separation ------------------------------------------------------------------------

class IdentityBoundaryTests(unittest.TestCase):
    STDLIB = {"__future__", "ast", "dataclasses", "hashlib", "json", "pathlib", "re", "types", "typing"}

    def test_owner_layer_is_project_neutral_stdlib_only(self):
        for path, module, level in _imports(OWNER_PKG):
            if level == 0:
                self.assertIn(module.split(".")[0], self.STDLIB, f"{path} imports {module}")
        for path in OWNER_PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for project_term in ("atlas", "sigma", "alpha lead", "holdout", "taint", "h4", "broker"):
                self.assertNotIn(project_term, text, f"{path} contains project-specific term {project_term!r}")

    def test_no_command_center_runtime_dependency(self):
        cc = re.compile(r"command[_\- ]?center", re.I)
        for pkg in (OWNER_PKG, ATLAS_PKG):
            for path, module, _ in _imports(pkg):
                self.assertIsNone(cc.search(module), f"{path} imports {module}")
            for path in pkg.rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                            and node.value.startswith(("/", "~")):
                        self.assertIsNone(cc.search(node.value), f"{path} references a Command Center path")
        for path in (ROOT / "atlas2").rglob("*.py"):
            self.assertNotIn("owner_dev_policy", path.read_text(encoding="utf-8"))

    def test_atlas_depends_on_owner_layer_one_way(self):
        atlas_uses_owner = any(m.startswith("tools.owner_dev_policy") for _, m, _ in _imports(ATLAS_PKG))
        self.assertTrue(atlas_uses_owner)
        self.assertFalse(any("atlas" in m for _, m, _ in _imports(OWNER_PKG)))

    def test_projection_and_events_are_project_owned_outputs(self):
        h = Harness(self)
        h.sup.intake(h.contract("id-proj"))
        h.sup.run("id-proj")
        p = projections.build_projection(h.store, "id-proj", policy=OwnerDevelopmentPolicy())
        self.assertEqual(p["project_id"], project.PROJECT_ID)
        exported = projections.export_events(h.store)
        self.assertEqual({e["project_id"] for e in exported}, {project.PROJECT_ID})
        out = h.tmp / "export" / "events.jsonl"
        events.append_jsonl(out, exported)
        self.assertEqual([p.name for p in out.parent.iterdir()], ["events.jsonl"])


# 2 -- monitoring projection ----------------------------------------------------------------------

class MonitoringProjectionTests(unittest.TestCase):
    def test_done_task_projection_contract(self):
        h = Harness(self)
        h.sup.intake(h.contract("mon-done"))
        h.sup.run("mon-done")
        p = projections.build_projection(h.store, "mon-done", policy=OwnerDevelopmentPolicy())
        task = h.store.get_task("mon-done")
        self.assertEqual((p["state"], p["terminal_result"], p["health"]["status"]), ("DONE", "DONE", "terminal"))
        self.assertEqual((p["qualification"]["status"], p["review"]["status"]), ("PASS", "APPROVE"))
        self.assertEqual(p["git"]["head_sha"], task["head_sha"])
        self.assertEqual(p["git"]["approved_head_sha"], task["head_sha"])
        self.assertEqual(p["priority"], "NORMAL")
        self.assertIsNotNone(p["last_checkpoint"])
        self.assertTrue(p["evidence_refs"])
        self.assertEqual(p["last_event_id"], projections.export_events(h.store, "mon-done")[-1]["event_id"])
        self.assertTrue(p["next_action"].startswith("none: task is terminal"))

    def test_waiting_projection_names_owner_action(self):
        h = Harness(self)
        h.sup.intake(_b1(h, "mon-wait"))
        h.sup.run("mon-wait")
        p = projections.build_projection(h.store, "mon-wait", policy=OwnerDevelopmentPolicy())
        self.assertEqual((p["state"], p["health"]["status"]), ("APPROVAL", "waiting"))
        self.assertEqual(len(p["approvals_needed"]), 1)
        self.assertIn(f"approve {p['approvals_needed'][0]} --by owner", p["next_action"])
        self.assertEqual(p["responsible"]["role"], "owner")
        self.assertEqual(p["last_checkpoint"]["trigger"], "waiting")

    def test_stale_and_blocked_health(self):
        h = Harness(self, sim.Script(provider_errors={"planner": 3}))
        h.sup.intake(h.contract("mon-blocked"))
        h.sup.run("mon-blocked")
        p = projections.build_projection(h.store, "mon-blocked", policy=OwnerDevelopmentPolicy())
        self.assertEqual(p["health"]["status"], "blocked")
        self.assertEqual(p["blockers"][0]["code"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(p["next_action"], f"{project.CLI} resume mon-blocked")
        h.sup.intake(h.contract("mon-stale", scope_paths=["atlas2/other"]))
        h.clock.advance(3 * HOUR_US)
        p = projections.build_projection(h.store, "mon-stale", policy=OwnerDevelopmentPolicy())
        self.assertEqual(p["health"]["status"], "stale")

    def test_projection_schema_is_strict(self):
        h = Harness(self)
        h.sup.intake(h.contract("mon-strict"))
        p = projections.build_projection(h.store, "mon-strict", policy=OwnerDevelopmentPolicy())
        for bad in ({**p, "next_action": "run a\nor run b"}, {k: v for k, v in p.items() if k != "git"},
                    {**p, "authority": "admin"}, {**p, "priority": "URGENT"}):
            with self.assertRaises(SchemaError):
                monitoring.validate_projection(bad)


# 3 -- event / graph export ------------------------------------------------------------------------

class EventExportTests(unittest.TestCase):
    def test_export_is_deterministic_idempotent_and_linked(self):
        h = Harness(self)
        h.sup.intake(h.contract("ev-1"))
        h.sup.run("ev-1")
        first, second = projections.export_events(h.store), projections.export_events(h.store)
        self.assertEqual(first, second)
        ids = [e["event_id"] for e in first]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("lease_acquired", {e["event_type"] for e in first})
        for prev, cur in zip(first, first[1:]):
            self.assertEqual(cur["parent_event_ids"], [prev["event_id"]])
        out = h.tmp / "events.jsonl"
        self.assertEqual(events.append_jsonl(out, first), len(first))
        self.assertEqual(events.append_jsonl(out, second), 0)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), len(first))
        transitions = [e for e in first if e["event_type"] == "transition"]
        self.assertEqual(transitions[-1]["to_state"], "DONE")
        self.assertTrue(any(e["test_refs"] for e in first) and any(e["review_refs"] for e in first))

    def test_conflicting_content_for_known_event_id_is_refused(self):
        h = Harness(self)
        h.sup.intake(h.contract("ev-2"))
        exported = projections.export_events(h.store)
        tampered = dict(exported[0], summary="rewritten history")
        with self.assertRaises(SchemaError):
            events.new_events(exported, [tampered])
        with self.assertRaises(SchemaError):  # event_id must be derived from (project_id, source_ref)
            events.validate_event(dict(exported[0], event_id="ev_" + "0" * 32))

    def test_event_summary_is_redacted_and_bounded(self):
        e = events.make_event(project_id="p", run_id="r", source_ref="journal:x", event_type="note", timestamp_us=1,
                              actor_role="operator", summary="api_key=sk-ant-SECRETSECRET123 " + "x" * 2000)
        self.assertNotIn("SECRETSECRET", e["summary"])
        self.assertLess(len(e["summary"]), 600)
        with self.assertRaises(SchemaError):
            events.validate_event(dict(e, summary="token=abc123"))


# 4 -- priority -----------------------------------------------------------------------------------

class PriorityTests(unittest.TestCase):
    def test_queue_order_follows_priority_then_age(self):
        items = [{"task_id": "b", "priority": "LOW", "created_us": 1},
                 {"task_id": "a", "priority": "CRITICAL_BLOCKER", "created_us": 3},
                 {"task_id": "c", "priority": "NORMAL", "created_us": 2},
                 {"task_id": "d", "priority": "NORMAL", "created_us": 1}]
        self.assertEqual([i["task_id"] for i in classification.queue_order(items)], ["a", "d", "c", "b"])
        self.assertEqual(len(classification.PRIORITIES), 8)

    def test_priority_never_bypasses_gates(self):
        h = Harness(self)
        h.sup.intake(h.contract("pr-low", priority="LOW", scope_paths=["atlas2/low"]))
        blocked = h.sup.intake(_b1(h, "pr-crit-noexp", priority="CRITICAL_BLOCKER", experiment=None,
                                   holdout_access=None))
        self.assertEqual((blocked["state"], blocked["block_code"]), ("BLOCKED", "EXPERIMENT_REQUIRED"))
        h.sup.intake(_b1(h, "pr-crit", priority="CRITICAL_BLOCKER"))
        results = h.sup.run_all()
        self.assertEqual([r.task_id for r in results], ["pr-crit", "pr-low"])
        self.assertEqual(h.store.get_task("pr-crit")["state"], "APPROVAL")  # owner gate still applies
        self.assertTrue(results[0].waiting)
        self.assertEqual(h.store.get_task("pr-crit-noexp")["state"], "BLOCKED")
        self.assertEqual(h.store.get_task("pr-low")["state"], "DONE")

    def test_priority_and_effort_override_change_no_policy_outcome(self):
        base = sim.contract("pr-same", "0" * 40, declared_class="B", impact_areas=B1_AREAS,
                            scope_paths=["atlas2/evaluate"], experiment=sim.experiment())
        low = TaskContract.from_dict(dict(base, priority="LOW"))
        crit = TaskContract.from_dict(dict(base, priority="CRITICAL_BLOCKER", effort_override="routine"))
        for a, b in ((classify(low), classify(crit)),):
            self.assertEqual(a, b)
            self.assertEqual(required_checks(a, low), required_checks(b, crit))
            self.assertEqual(approval_categories(a), approval_categories(b))
        self.assertEqual(project.effort_for("C", architecture_significant=False, override="routine"), "routine")
        self.assertEqual(project.effort_for("A", architecture_significant=True, override=None), "deep")


# 5 -- provider failover --------------------------------------------------------------------------

class ProviderFailoverTests(unittest.TestCase):
    def test_exhaustion_checkpoints_and_successor_gets_identical_handoff(self):
        script = sim.Script()
        primary = FakeExecutor("codex", "impl-a", _exhausting(script.implementer))
        successor = FakeExecutor("claude", "impl-b", script.implementer)
        reviewer = FakeExecutor("gemini-qualified-test", "rev", script.reviewer)
        h = _chain_harness(self, [primary, successor], [reviewer], script)
        h.sup.intake(h.contract("fo-1"))
        h.sup.run("fo-1")
        self.assertEqual(h.store.get_task("fo-1")["state"], "DONE")
        self.assertEqual(len(primary.handoffs), 1)  # exhaustion: no same-provider retry
        self.assertEqual(primary.handoffs[0], successor.handoffs[0])
        entries = h.store.journal_entries("fo-1")
        failover = [e for e in entries if e["event_type"] == "provider_failover"]
        self.assertEqual(len(failover), 1)
        self.assertEqual(failover[0]["payload"]["handoff_digest"], digest(HANDOFF_V1, successor.handoffs[0]))
        cp = [e for e in entries if e["event_type"] == "checkpoint" and e["seq"] < failover[0]["seq"]][-1]["payload"]
        self.assertEqual(cp["trigger"], "provider_exhausted")
        self.assertEqual(cp["executor"], primary.executor_id)
        self.assertEqual(cp["head_sha"], h.store.get_task("fo-1")["base_sha"])
        self.assertEqual(cp["owned_paths"], ["atlas2/core"])
        self.assertEqual(cp["next_action"], f"{project.CLI} run fo-1")
        impl_runs = [r for r in h.store.agent_runs("fo-1") if r["role"] == "implementer"]
        self.assertEqual([r["executor_id"] for r in impl_runs], [successor.executor_id])

    def test_whole_chain_exhausted_blocks_recoverably_with_checkpoint(self):
        script = sim.Script()
        a = FakeExecutor("codex", "a", _exhausting(script.implementer, times=1))
        b = FakeExecutor("claude", "b", _exhausting(script.implementer, times=1))
        h = _chain_harness(self, [a, b], [FakeExecutor("third", "rev", script.reviewer)], script)
        h.sup.intake(h.contract("fo-all"))
        h.sup.run("fo-all")
        t = h.store.get_task("fo-all")
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "PROVIDER_UNAVAILABLE"))
        last_cp = h.events("fo-all", "checkpoint")[-1]["payload"]
        self.assertEqual((last_cp["trigger"], last_cp["state"]), ("provider_exhausted", "BLOCKED"))
        from tools.atlas_dev_workflow.supervisor import resume
        resume(h.store, "fo-all", actor="owner")
        h.sup.run("fo-all")
        self.assertEqual(h.store.get_task("fo-all")["state"], "DONE")

    def test_cli_exhaustion_is_classified_and_not_retried(self):
        d = Path(tempfile.mkdtemp(prefix="devwf-fo-"))
        self.addCleanup(shutil.rmtree, d, True)
        script = d / "limited.py"
        script.write_text(textwrap.dedent("""
            import sys
            sys.stdin.read()
            print("Error: rate limit exceeded (429)", file=sys.stderr)
            sys.exit(1)
        """), encoding="utf-8")
        with self.assertRaises(ProviderExhausted):
            CliExecutor("x", "m", [sys.executable, str(script)]).run({"instructions": "", "step_key": "s"})

    def test_executor_specs_carry_no_permission_and_chains_come_from_config(self):
        execs = providers.default_executors()
        providers.validate_role_chains(execs, providers.default_role_chains(), ["planner", "implementer", "qa", "reviewer"])
        with self.assertRaises(SchemaError):
            providers.validate_executor_spec("claude", dict(execs["claude"], permissions=["merge"]))
        with self.assertRaises(SchemaError):  # gemini is research-only unless explicitly qualified
            providers.validate_role_chains(execs, dict(providers.default_role_chains(), implementer=["gemini"]),
                                           ["implementer"])
        qualified = dict(execs, gemini=dict(execs["gemini"], qualified_roles=["research", "implementer"]))
        providers.validate_role_chains(qualified, dict(providers.default_role_chains(), implementer=["gemini"]),
                                       ["implementer"])


# 6 -- reviewer independence ----------------------------------------------------------------------

class ReviewerIndependenceTests(unittest.TestCase):
    def test_reviewer_switches_provider_when_implementer_fails_over_to_it(self):
        script = sim.Script()
        impl = [FakeExecutor("codex", "impl", _exhausting(script.implementer)),
                FakeExecutor("claude", "impl", script.implementer)]
        rev = [FakeExecutor("claude", "review", script.reviewer), FakeExecutor("codex", "review", script.reviewer)]
        h = _chain_harness(self, impl, rev, script)
        h.sup.intake(h.contract("ri-1"))
        h.sup.run("ri-1")
        self.assertEqual(h.store.get_task("ri-1")["state"], "DONE")
        review = [e for e in h.events("ri-1", "transition") if e["to_state"] == "APPROVAL"][0]["payload"]["evidence"]
        self.assertEqual(review["implementer_executors"], ["fake:claude:impl"])
        self.assertEqual(review["reviewer_executor"], "fake:codex:review")
        self.assertEqual(rev[0].calls, [])
        dod = [e for e in h.events("ri-1", "transition") if e["to_state"] == "DONE"][0]["payload"]["evidence"]
        self.assertTrue(dod["definition_of_done"]["owner"]["independent_review_passed"])

    def test_reviewer_must_be_independent_of_every_implementer(self):
        script = sim.Script(qa_fail_times=1)
        calls = {"n": 0}

        def codex_then_exhausted(handoff):
            calls["n"] += 1
            return ProviderExhausted("usage limit") if calls["n"] > 1 else script.implementer(handoff)
        impl = [FakeExecutor("codex", "impl", codex_then_exhausted), FakeExecutor("claude", "impl", script.implementer)]
        rev = [FakeExecutor("claude", "review", script.reviewer), FakeExecutor("codex", "review", script.reviewer)]
        h = _chain_harness(self, impl, rev, script)
        h.sup.intake(h.contract("ri-2"))
        h.sup.run("ri-2")
        t = h.store.get_task("ri-2")
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "REVIEWER_NOT_INDEPENDENT"))
        self.assertEqual(rev[0].calls + rev[1].calls, [])

    def test_config_without_any_independent_reviewer_is_refused(self):
        script = sim.Script()
        impl = [FakeExecutor("codex", "i", script.implementer), FakeExecutor("claude", "i", script.implementer)]
        with self.assertRaises(ContractError):
            _chain_harness(self, impl, [FakeExecutor("claude", "r", script.reviewer)], script)


# 7 -- context truncation -------------------------------------------------------------------------

class ContextTruncationTests(unittest.TestCase):
    def test_reference_truncation_propagates_to_handoff_journal_projection_and_checkpoint(self):
        h = Harness(self)
        index = {"entries": [{"ref_id": f"ref_{i}", "kind": "atlas2_code", "path": f"atlas2/core/m{i}.py",
                              "sha256": "0" * 64, "title": "core module", "tags": []} for i in range(12)]}
        h.sup = Supervisor(h.store, h.bindings, workspace=h.workspace, merge_gateway=h.gateway,
                           reference_index=index)
        h.sup.intake(h.contract("ctx-1"))
        h.sup.run("ctx-1")
        planner_handoff = h.bindings["planner"].handoffs[0]
        self.assertEqual(planner_handoff["context"], {"truncated": True, "omitted": {"references": 4}})
        self.assertEqual(len(planner_handoff["references"]), 8)
        packets = h.events("ctx-1", "agent_packet")
        self.assertTrue(all(p["payload"]["context_truncated"] for p in packets))
        p = projections.build_projection(h.store, "ctx-1", policy=OwnerDevelopmentPolicy())
        self.assertTrue(p["context_truncated"])
        cp = h.events("ctx-1", "checkpoint")[-1]["payload"]
        self.assertTrue(any("truncated context" in r for r in cp["risks"]))

    def test_untruncated_context_is_explicitly_complete(self):
        h = Harness(self)
        h.sup.intake(h.contract("ctx-0"))
        h.sup.run("ctx-0")
        self.assertEqual(h.bindings["planner"].handoffs[0]["context"], {"truncated": False, "omitted": {}})
        self.assertFalse(projections.build_projection(h.store, "ctx-0", policy=OwnerDevelopmentPolicy())["context_truncated"])

    def test_truncated_agent_output_is_never_accepted(self):
        h = Harness(self)
        real = h.bindings["planner"]

        class Truncating:
            provider, model, kind = "trunc", "m", "fake"
            executor_id = "fake:trunc:m"

            def run(self, handoff):
                return ExecResult(real.run(handoff).text, truncated=True)
        bindings = dict(h.bindings, planner=Truncating())
        h.sup = Supervisor(h.store, bindings, workspace=h.workspace, merge_gateway=h.gateway)
        h.sup.intake(h.contract("ctx-out"))
        h.sup.run("ctx-out")
        t = h.store.get_task("ctx-out")
        self.assertEqual((t["state"], t["block_code"]), ("FAILED", "INVALID_AGENT_OUTPUT"))
        self.assertIn("truncated", t["block_reason"])


# 8 -- usage metrics and budgets ------------------------------------------------------------------

class UsageTelemetryTests(unittest.TestCase):
    def test_usage_sanitization_is_numeric_bounded_and_optional(self):
        self.assertIsNone(compute.sanitize_usage(None))
        self.assertIsNone(compute.sanitize_usage({"api_key": "sk-ant-x"}))
        clean = compute.sanitize_usage({"input_tokens": 10, "output_tokens": -1, "cost_usd_micros": 10**13,
                                        "compute_ms": 5.5, "api_key": "sk-ant-secret", "input_text": "prompt"})
        self.assertEqual(clean, {"input_tokens": 10})

    def test_reported_usage_flows_to_journal_projection_and_events(self):
        h = Harness(self, sim.Script(usage={"input_tokens": 100, "output_tokens": 20, "secret": "token=SECRETVALUE9"}))
        h.sup.intake(h.contract("use-1"))
        h.sup.run("use-1")
        packets = h.events("use-1", "agent_packet")
        self.assertTrue(all(p["payload"]["usage"] == {"input_tokens": 100, "output_tokens": 20} for p in packets))
        p = projections.build_projection(h.store, "use-1", policy=OwnerDevelopmentPolicy())
        self.assertEqual(p["usage"]["totals"], {"input_tokens": 100 * len(packets), "output_tokens": 20 * len(packets)})
        self.assertNotIn("SECRETVALUE9", json.dumps(projections.export_events(h.store)))
        self.assertNotIn("SECRETVALUE9", json.dumps(h.store.journal_entries("use-1")))

    def test_unreported_usage_is_unknown_not_zero_claimed(self):
        h = Harness(self)
        h.sup.intake(h.contract("use-none"))
        h.sup.run("use-none")
        p = projections.build_projection(h.store, "use-none", policy=OwnerDevelopmentPolicy())
        self.assertEqual((p["usage"]["reported"], p["usage"]["totals"]), (False, {}))

    def test_budget_stops_before_the_next_agent_call(self):
        h = Harness(self, sim.Script(usage={"input_tokens": 150}))
        h.sup.intake(h.contract("use-budget", budget={"max_total_tokens": 300}))
        h.sup.run("use-budget")
        t = h.store.get_task("use-budget")
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "BUDGET_EXCEEDED"))
        self.assertEqual(len(h.events("use-budget", "agent_packet")), 2)
        with self.assertRaises(ContractError):
            TaskContract.from_dict(sim.contract("bad-budget", "0" * 40, budget={"max_tokens": 1}))


# 9 -- finding classification ---------------------------------------------------------------------

class FindingClassificationTests(unittest.TestCase):
    def test_all_classifications_accepted_and_dispositions_need_reasons(self):
        for cls in classification.FINDING_CLASSES:
            classification.Finding.from_dict({"finding_id": "F1", "classification": cls, "summary": "s"})
        with self.assertRaises(SchemaError):
            classification.Finding.from_dict({"finding_id": "F1", "classification": "NICE_TO_HAVE", "summary": "s"})
        with self.assertRaises(SchemaError):  # rejecting a review finding requires a recorded reason
            classification.Finding.from_dict({"finding_id": "F1", "classification": "MUST_FIX_BEFORE_PRODUCTION",
                                              "summary": "s", "disposition": "REJECTED_INVALID"})
        open_impl = classification.Finding("F", "MUST_FIX_BEFORE_IMPLEMENTATION", "s")
        prod = classification.Finding("F", "MUST_FIX_BEFORE_PRODUCTION", "s")
        self.assertTrue(classification.blocks_development_done(open_impl))
        self.assertFalse(classification.blocks_development_done(prod))
        self.assertTrue(classification.blocks_production(prod))
        self.assertFalse(classification.blocks_development_done(
            classification.Finding("F", "MUST_FIX_BEFORE_IMPLEMENTATION", "s", "FIXED")))

    def test_approval_with_open_must_fix_finding_goes_to_fixing(self):
        script = sim.Script()
        reviews = {"n": 0}

        def reviewer(handoff):
            reviews["n"] += 1
            packet = script.reviewer(handoff)
            if reviews["n"] == 1:
                packet["payload"]["findings"] = [{"severity": "major", "summary": "duplicated digest logic",
                                                  "finding_id": "R1", "classification": "MUST_FIX_BEFORE_IMPLEMENTATION"}]
            return packet

        def implementer(handoff):
            packet = script.implementer(handoff)
            if handoff["state"] == "FIXING":
                packet["payload"]["finding_dispositions"] = [
                    {"finding_id": "R1", "classification": "MUST_FIX_BEFORE_IMPLEMENTATION",
                     "summary": "duplicated digest logic", "disposition": "FIXED"},
                    {"finding_id": "R2", "classification": "ACCEPTABLE_TECHNICAL_DEBT", "summary": "naming",
                     "disposition": "REJECTED_INVALID", "reason": "name matches ADR-003 vocabulary"}]
            return packet
        h = Harness(self, script)
        h.bindings["reviewer"].responder = reviewer
        h.bindings["implementer"].responder = implementer
        h.sup.intake(h.contract("fd-1"))
        h.sup.run("fd-1")
        self.assertEqual(h.store.get_task("fd-1")["state"], "DONE")
        self.assertIn(("REVIEW", "FIXING"), h.transitions("fd-1"))
        fix = [e for e in h.events("fd-1", "transition") if e["from_state"] == "FIXING"][0]["payload"]["evidence"]
        self.assertEqual(fix["finding_dispositions"][1]["reason"], "name matches ADR-003 vocabulary")

    def test_architecture_significant_work_requires_passed_maintainability_audit(self):
        audit = {"passed": True, "findings": [{"finding_id": "Z1", "classification": "DEFERRED_SCALE_CONCERN",
                                               "summary": "single-writer SQLite", "disposition": "DEFERRED",
                                               "reason": "single-owner local runtime"}]}
        h = Harness(self, sim.Script(review_overrides={"maintainability_audit": audit}))
        h.sup.intake(h.contract("arch-ok", architecture_significant=True))
        h.sup.run("arch-ok")
        self.assertEqual(h.store.get_task("arch-ok")["state"], "DONE")
        missing = Harness(self)
        missing.sup.intake(missing.contract("arch-missing", architecture_significant=True))
        missing.sup.run("arch-missing")
        t = missing.store.get_task("arch-missing")
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "FIX_CYCLES_EXHAUSTED"))
        self.assertIn("maintainability audit", t["block_reason"])


# 10 -- composition of Atlas policy with owner policy ---------------------------------------------

class PolicyCompositionTests(unittest.TestCase):
    def test_owner_dod_is_composed_not_replaced(self):
        owner_ok = {k: True for k in done.OWNER_DOD}
        self.assertTrue(done.evaluate_done(owner_ok, {"atlas_check": True}).done)
        self.assertFalse(done.evaluate_done(owner_ok, {}).done)  # project must contribute its own DoD
        shadow = done.evaluate_done(owner_ok, {"independent_review_passed": True, "atlas_check": True})
        self.assertFalse(shadow.done)
        missing = dict(owner_ok)
        missing.pop("checkpoint_recorded")
        self.assertIn("checkpoint_recorded", done.evaluate_done(missing, {"atlas_check": True}).failed)
        self.assertFalse(done.evaluate_done(owner_ok, {"atlas_check": False}).done)

    def test_done_evidence_records_owner_and_atlas_requirements(self):
        h = Harness(self)
        h.sup.intake(h.contract("comp-1"))
        h.sup.run("comp-1")
        dod = [e for e in h.events("comp-1", "transition") if e["to_state"] == "DONE"][0]["payload"]["evidence"]
        self.assertEqual(set(dod["definition_of_done"]["owner"]), set(done.OWNER_DOD))
        self.assertTrue(all(dod["definition_of_done"]["owner"].values()))
        self.assertTrue(all(dod["definition_of_done"]["project"].values()))
        self.assertEqual(dod["boundary"]["strategy_promoted"], False)

    def test_atlas_gates_still_apply_under_owner_policy(self):
        h = Harness(self)
        t = h.sup.intake(_b1(h, "comp-holdout", priority="CRITICAL_BLOCKER", effort_override="deep",
                             holdout_access={"requested": True, "via_preregistered_path": False}))
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "HOLDOUT_ACCESS_DENIED"))
        live = h.sup.intake(h.contract("comp-live", declared_class="C", impact_areas=["production_live"],
                                       scope_paths=["bridges/live"], execution_stage="limited_live",
                                       priority="CRITICAL_BLOCKER"))
        self.assertEqual(live["block_code"], "SEPARATE_OWNER_AUTHORIZATION_REQUIRED")

    def test_glossary_composition(self):
        self.assertIn("holdout", project.GLOSSARY)
        self.assertIn("checkpoint", project.GLOSSARY)
        for term in ("holdout", "taint", "h4 last impulse"):
            self.assertNotIn(term, glossary.OWNER_GLOSSARY)
        self.assertIn("never means extra layers or overengineering", glossary.lookup(project.GLOSSARY, "OCD-style"))
        self.assertEqual(glossary.lookup(project.GLOSSARY, "root"), glossary.lookup(project.GLOSSARY, "owner"))
        with self.assertRaises(SchemaError):
            glossary.compose_glossary({"checkpoint": ("redefined", ())})
        with self.assertRaises(SchemaError):
            glossary.compose_glossary({"my term": ("x", ("failover",))})

    def test_owner_policy_settings_are_bounded(self):
        with self.assertRaises(SchemaError):
            OwnerDevelopmentPolicy(checkpoint_interval_s=3600)  # at least every 30 minutes
        with self.assertRaises(SchemaError):
            OwnerDevelopmentPolicy.from_dict({"reviewer_independence": "same_is_fine"})
        self.assertEqual(OwnerDevelopmentPolicy.from_dict({}).reviewer_independence, "distinct_provider")


# durable coordination: checkpoints, lanes, control requests ----------------------------------------

class DurableCoordinationTests(unittest.TestCase):
    def test_interval_checkpoint_and_checkpoint_contract(self):
        h = Harness(self)
        h.sup.intake(_b1(h, "cp-1"))
        h.sup.run("cp-1")
        h.clock.advance(31 * 60 * 1_000_000)
        h.sup.run("cp-1")
        triggers = [e["payload"]["trigger"] for e in h.events("cp-1", "checkpoint")]
        self.assertIn("risky_command", triggers)
        self.assertIn("waiting", triggers)
        self.assertIn("interval", triggers)
        cp = h.events("cp-1", "checkpoint")[-1]["payload"]
        with self.assertRaises(SchemaError):
            owner_checkpoint.validate_checkpoint({k: v for k, v in cp.items() if k != "next_action"})
        with self.assertRaises(SchemaError):
            owner_checkpoint.validate_checkpoint(dict(cp, head_sha="HEAD"))

    def test_owned_paths_are_exclusive_per_active_lane(self):
        h = Harness(self)
        h.sup.intake(h.contract("lane-1", scope_paths=["atlas2/core"]))
        t = h.sup.intake(h.contract("lane-2", scope_paths=["atlas2/core/units.py"]))
        self.assertEqual((t["state"], t["block_code"]), ("BLOCKED", "OWNED_PATHS_CONFLICT"))
        h.sup.run("lane-1")
        self.assertEqual(h.sup.intake(h.contract("lane-3", scope_paths=["atlas2/core/units.py"]))["state"], "NEW_TASK")

    def _request(self, **overrides):
        req = {"schema_version": monitoring.CONTROL_REQUEST_V1, "project_id": project.PROJECT_ID,
               "request_id": "req-1", "action": "pause", "target": "ctl-1", "requested_by": "owner",
               "channel": "command_center", "reason": "owner pause", "created_us": 1}
        req.update(overrides)
        return req

    def test_control_requests_are_enforced_by_atlas(self):
        h = Harness(self)
        h.sup.intake(h.contract("ctl-1"))
        with self.assertRaises(PolicyViolation):  # the channel grants nothing; the requester must be authorized
            apply_control(h.store, self._request(request_id="req-0", requested_by="command-center-service"))
        refused = [e for e in h.events("ctl-1", "control_request")]
        self.assertEqual(refused[0]["payload"]["accepted"], False)
        self.assertEqual(h.store.get_task("ctl-1")["state"], "NEW_TASK")
        out = apply_control(h.store, self._request())
        self.assertEqual((out["accepted"], h.store.get_task("ctl-1")["state"]), (True, "PAUSED"))
        self.assertTrue(apply_control(h.store, self._request())["replayed"])  # idempotent by request_id
        with self.assertRaises(PolicyViolation):
            apply_control(h.store, self._request(reason="different content, same id"))
        with self.assertRaises(PolicyViolation):
            apply_control(h.store, self._request(request_id="req-x", project_id="sigma-workoffice"))
        with self.assertRaises(SchemaError):  # no field can carry authority or activation
            apply_control(h.store, self._request(request_id="req-y", activation_allowed=True))
        self.assertEqual(apply_control(h.store, self._request(request_id="req-2", action="resume"))["accepted"], True)
        self.assertEqual(apply_control(h.store, self._request(request_id="req-3", action="recover"))["accepted"], True)

    def test_control_approval_requires_owner(self):
        h = Harness(self)
        h.sup.intake(_b1(h, "ctl-apr"))
        h.sup.run("ctl-apr")
        apr = h.store.approvals(task_id="ctl-apr", status="PENDING")[0]["approval_id"]
        with self.assertRaises(PolicyViolation):
            apply_control(h.store, self._request(request_id="a-1", action="approve", target=apr, requested_by="operator"))
        apply_control(h.store, self._request(request_id="a-2", action="approve", target=apr))
        h.sup.run("ctl-apr")
        self.assertEqual(h.store.get_task("ctl-apr")["state"], "DONE")

    def test_default_control_authority_covers_every_action(self):
        self.assertEqual(set(project.DEFAULT_CONTROL_AUTHORITY), set(monitoring.CONTROL_ACTIONS))

    def test_external_research_is_untrusted_evidence(self):
        from tools.atlas_dev_workflow.supervisor import add_external_research
        h = Harness(self)
        h.sup.intake(h.contract("rs-1"))
        add_external_research(h.store, "rs-1", actor="gemini-research", source="web", text="popular opinion; api_key=zzz")
        e = h.events("rs-1", "external_research")[0]["payload"]
        self.assertEqual((e["authority"], e["trust"]), ("none", "untrusted_until_independent_review"))
        self.assertNotIn("zzz", e["excerpt"])



class OwnerPolicyCliTests(unittest.TestCase):
    def _run(self, *argv):
        import contextlib
        import io
        from tools.atlas_dev_workflow import cli
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        text = buf.getvalue() or err.getvalue()
        return code, json.loads(text) if text.strip() else None

    def test_monitor_events_control_checkpoint_glossary_commands(self):
        d = Path(tempfile.mkdtemp(prefix="devwf-cli-owner-"))
        self.addCleanup(shutil.rmtree, d, True)
        repo, base = sim.make_repo(d)
        common = ["--repo", str(repo), "--state-dir", str(d / "state")]
        self.assertEqual(self._run(*common, "init")[0], 0)
        code, report = self._run(*common, "validate")
        self.assertEqual((code, report["bindings_ok"]), (0, False))  # real executors ship disabled
        self.assertEqual(report["role_chains"]["implementer"], ["codex", "claude"])
        self.assertEqual(report["owner_policy"]["reviewer_independence"], "distinct_provider")
        contract = d / "t.json"
        contract.write_text(json.dumps(sim.contract("cli-own", base, priority="HIGH")), encoding="utf-8")
        self._run(*common, "task", "create", str(contract))
        code, views = self._run(*common, "monitor")
        self.assertEqual((code, views[0]["run_id"], views[0]["priority"]), (0, "cli-own", "HIGH"))
        code, cp = self._run(*common, "checkpoint", "cli-own", "--trigger", "context_switch")
        self.assertEqual((code, cp["written"], cp["checkpoint"]["state"]), (0, True, "NEW_TASK"))
        code, first = self._run(*common, "events")
        code2, second = self._run(*common, "events")
        self.assertEqual((code, code2, second["appended"]), (0, 0, 0))
        self.assertEqual(first["appended"], first["exported"])
        request = d / "pause.json"
        request.write_text(json.dumps({
            "schema_version": monitoring.CONTROL_REQUEST_V1, "project_id": project.PROJECT_ID, "request_id": "cc-1",
            "action": "pause", "target": "cli-own", "requested_by": "owner", "channel": "command_center",
            "reason": "", "created_us": 1}), encoding="utf-8")
        code, out = self._run(*common, "control", str(request))
        self.assertEqual((code, out["accepted"]), (0, True))
        self.assertEqual(self._run(*common, "monitor", "cli-own")[1][0]["state"], "PAUSED")
        code, term = self._run("glossary", "task", "lane")
        self.assertEqual(code, 0)
        self.assertIn("one worktree", term["definition"])
        self.assertEqual(self._run("glossary", "nonexistent-term")[0], 1)


if __name__ == "__main__":
    unittest.main()
