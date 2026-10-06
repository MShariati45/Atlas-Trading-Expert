"""Component tests: contracts, executors, references, store schema, CLI and architecture boundary."""
import ast
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from devwf_harness import Harness

from tools.atlas_dev_workflow import cli
from tools.atlas_dev_workflow import simulation as sim
from tools.atlas_dev_workflow.contracts import PACKET_V1, TaskContract, parse_packet
from tools.atlas_dev_workflow.errors import ContractError, ProviderError, StateStoreError
from tools.atlas_dev_workflow.executors import CliExecutor, build_executor, discover_clis, extract_packet
from tools.owner_dev_policy.redaction import redact
from tools.atlas_dev_workflow.references import build_index, query
from tools.atlas_dev_workflow.store import Store

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "tools" / "atlas_dev_workflow"


def _tmp(case) -> Path:
    d = Path(tempfile.mkdtemp(prefix="devwf-unit-"))
    case.addCleanup(shutil.rmtree, d, True)
    return d


class ContractTests(unittest.TestCase):
    def test_unknown_fields_and_bad_versions_rejected(self):
        base = sim.contract("c-ok", "0" * 40)
        TaskContract.from_dict(base)
        for bad in (dict(base, surprise=1), dict(base, schema_version="v0"), dict(base, base_sha="abc"),
                    dict(base, task_id="Bad Id"), dict(base, impact_areas=["made_up"]),
                    dict(base, scope_paths=["../outside"]), dict(base, execution_stage="live_now"),
                    dict(base, activation_allowed="yes")):
            with self.assertRaises(ContractError):
                TaskContract.from_dict(bad)

    def test_contract_digest_is_stable(self):
        a = TaskContract.from_dict(sim.contract("c-dig", "0" * 40))
        b = TaskContract.from_dict(json.loads(json.dumps(sim.contract("c-dig", "0" * 40))))
        self.assertEqual(a.digest, b.digest)
        self.assertEqual(TaskContract.from_dict(a.to_dict()).digest, a.digest)

    def test_packet_must_answer_its_handoff(self):
        packet = {"schema_version": PACKET_V1, "role": "reviewer", "kind": "review", "task_id": "t1", "step_key": "s1",
                  "payload": {"head_sha": "a" * 40, "verdict": "APPROVE", "findings": [], "promotion_claim": False}}
        parse_packet(packet, role="reviewer", expected_kind="review", task_id="t1", step_key="s1")
        for kwargs in ({"role": "qa", "expected_kind": "review"}, {"role": "reviewer", "expected_kind": "plan"}):
            with self.assertRaises(ContractError):
                parse_packet(packet, task_id="t1", step_key="s1", **kwargs)
        with self.assertRaises(ContractError):
            parse_packet(packet, role="reviewer", expected_kind="review", task_id="t1", step_key="stale")
        qa = {"schema_version": PACKET_V1, "role": "qa", "kind": "qa_report", "task_id": "t1", "step_key": "s1",
              "payload": {"head_sha": "a" * 40, "verdict": "PASS", "tests": [], "checks": {}}}
        with self.assertRaises(ContractError):  # no PASS without executed tests
            parse_packet(qa, role="qa", expected_kind="qa_report", task_id="t1", step_key="s1")


class ExecutorTests(unittest.TestCase):
    def test_redaction_of_common_secret_shapes(self):
        text = ("api_key=abc123 token: 'xyz' sk-ant-REDACTME0123456789 ghp_" + "a" * 30 +
                " AKIAABCDEFGHIJKLMNOP -----BEGIN RSA PRIVATE KEY-----\nzz\n-----END RSA PRIVATE KEY-----")
        out = redact(text)
        for secret in ("abc123", "xyz", "REDACTME", "a" * 30, "AKIAABCDEFGHIJKLMNOP", "zz"):
            self.assertNotIn(secret, out)

    def test_extract_packet_from_fenced_output(self):
        self.assertEqual(extract_packet('noise\n```json\n{"a": 1}\n```\n'), {"a": 1})
        with self.assertRaises(ContractError):
            extract_packet("no json here")

    def test_cli_executor_runs_local_program_with_scrubbed_env_and_bounded_output(self):
        d = _tmp(self)
        script = d / "fake_agent_cli.py"
        script.write_text(textwrap.dedent("""
            import json, os, sys
            prompt = sys.stdin.read()
            handoff = json.loads(prompt.split("HANDOFF JSON:\\n", 1)[1])
            print("debug api_key=shouldnotleak")
            print(json.dumps({"leaked_env": "DEVWF_FAKE_SECRET" in os.environ, "step": handoff["step_key"],
                              "cwd": os.getcwd()}))
        """), encoding="utf-8")
        os.environ["DEVWF_FAKE_SECRET"] = "s3cr3t"
        self.addCleanup(os.environ.pop, "DEVWF_FAKE_SECRET", None)
        ex = CliExecutor(provider="fakecli", model="m1", argv=[sys.executable, str(script)], timeout_s=30)
        out = ex.run({"instructions": "x", "step_key": "abc", "workdir": str(d)}).text
        payload = json.loads(out.splitlines()[-1])
        self.assertFalse(payload["leaked_env"])
        self.assertEqual(payload["step"], "abc")
        self.assertEqual(Path(payload["cwd"]).resolve(), d.resolve())
        self.assertNotIn("shouldnotleak", redact(out))

    def test_cli_executor_failures_are_provider_errors(self):
        d = _tmp(self)
        failing = d / "fail.py"
        failing.write_text("import sys; sys.exit(3)", encoding="utf-8")
        with self.assertRaises(ProviderError):
            CliExecutor("f", "m", [sys.executable, str(failing)]).run({"instructions": "", "step_key": "s"})
        with self.assertRaises(ProviderError):
            CliExecutor("f", "m", ["/nonexistent/agent-cli"]).run({"instructions": "", "step_key": "s"})
        slow = d / "slow.py"
        slow.write_text("import time; time.sleep(5)", encoding="utf-8")
        with self.assertRaises(ProviderError):
            CliExecutor("f", "m", [sys.executable, str(slow)], timeout_s=1).run({"instructions": "", "step_key": "s"})

    def test_default_model_drops_model_flag(self):
        ex = CliExecutor("x", "default", [sys.executable, "-c", "import sys; print(sys.argv[1:])", "--model", "{model}"])
        self.assertEqual(ex.run({"instructions": "", "step_key": "s"}).text.strip(), "[]")

    def test_disabled_cli_bindings_fail_closed_and_discovery_never_executes(self):
        with self.assertRaises(ContractError):
            build_executor({"kind": "cli", "provider": "claude", "enabled": False})
        with self.assertRaises(ContractError):
            build_executor({"kind": "http", "provider": "x"})
        found = discover_clis(names=("definitely-not-installed-devwf",))
        self.assertEqual(found[0]["installed"], False)
        self.assertNotIn("version", found[0])


class ReferenceTests(unittest.TestCase):
    def test_index_is_deterministic_and_legacy_is_opt_in(self):
        a = build_index(ROOT, git_log_limit=5)
        b = build_index(ROOT, git_log_limit=5)
        self.assertEqual(a, b)
        kinds = {e["kind"] for e in a["entries"]}
        for kind in ("atlas2_contract", "atlas2_code", "atlas2_tests", "git_commit"):
            self.assertIn(kind, kinds)
        paths = {e["path"] for e in a["entries"]}
        for p in ("atlas2/research/holdout.py", "atlas2/research/registry.py", "atlas2/core/taint.py",
                  "docs/atlas2/adr/ADR-007-evolutionary-upgradeability.md"):
            self.assertIn(p, paths)
        hits = query(a, "holdout taint registry")
        self.assertTrue(hits and all(h["kind"] != "legacy_handoff" for h in hits))
        self.assertEqual(hits, query(a, "holdout taint registry"))
        legacy = query(a, "handoff rc17", include_legacy=True)
        self.assertTrue(any(h["kind"] == "legacy_handoff" for h in legacy))
        self.assertFalse(any(h["kind"] == "legacy_handoff" for h in query(a, "handoff rc17")))

    def test_external_design_reference_status(self):
        d = _tmp(self)
        f = d / "design.pdf"
        f.write_bytes(b"pdf")
        idx = build_index(ROOT, git_log_limit=0, external_refs=[
            {"path": str(f), "sha256": "0" * 64}, {"path": str(d / "missing.pdf"), "sha256": "0" * 64}])
        statuses = sorted(e["status"] for e in idx["entries"] if e["kind"] == "design_reference")
        self.assertEqual(statuses, ["hash_mismatch", "missing"])


class StoreSchemaTests(unittest.TestCase):
    def test_schema_version_recorded_and_newer_schema_refused(self):
        d = _tmp(self)
        s = Store(d / "s.sqlite3")
        self.assertEqual(s.schema_version(), 1)
        s.conn.execute("UPDATE schema_meta SET value='99' WHERE key='schema_version'")
        s.close()
        with self.assertRaises(StateStoreError):
            Store(d / "s.sqlite3")

    def test_reopen_is_idempotent(self):
        d = _tmp(self)
        Store(d / "s.sqlite3").close()
        s = Store(d / "s.sqlite3")
        self.assertEqual(s.schema_version(), 1)
        s.close()

    def test_external_research_is_evidence_without_authority(self):
        h = Harness(self)
        h.sup.intake(h.contract("research-lane"))
        from tools.atlas_dev_workflow.supervisor import add_external_research
        add_external_research(h.store, "research-lane", actor="operator", source="paper",
                              text="finding; token=abc123")
        seen = []
        real = h.bindings["planner"].responder
        h.bindings["planner"].responder = lambda handoff: (seen.append(handoff["prior_evidence"]), real(handoff))[1]
        h.sup.run("research-lane")
        lane = [e for e in seen[0] if e["role"] == "external_research"][0]
        self.assertEqual(lane["authority"], "none")
        self.assertNotIn("abc123", json.dumps(lane))
        self.assertEqual(h.store.get_task("research-lane")["state"], "DONE")


class CliTests(unittest.TestCase):
    def _run(self, *argv) -> tuple[int, dict | list | None]:
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        text = buf.getvalue() or err.getvalue()
        try:
            return code, json.loads(text) if text.strip() else None
        except ValueError:
            raise AssertionError(repr(text[:500]))

    def test_operator_cli_end_to_end_without_model_calls(self):
        d = _tmp(self)
        repo, base = sim.make_repo(d)
        common = ["--repo", str(repo), "--state-dir", str(d / "state")]
        code, init = self._run(*common, "init")
        self.assertEqual((code, init["schema_version"]), (0, 1))
        code, report = self._run(*common, "validate")
        self.assertEqual((code, report["bindings_ok"]), (0, False))  # real CLIs ship disabled
        contract_file = d / "c3.json"
        contract_file.write_text(json.dumps(sim.contract("cli-live", base, declared_class="C",
                                                         impact_areas=["production_live"], scope_paths=["bridges/live"],
                                                         execution_stage="limited_live")), encoding="utf-8")
        code, task = self._run(*common, "task", "create", str(contract_file))
        self.assertEqual((code, task["state"], task["block_code"]), (0, "BLOCKED", "SEPARATE_OWNER_AUTHORIZATION_REQUIRED"))
        ok_file = d / "a1.json"
        ok_file.write_text(json.dumps(sim.contract("cli-a1", base)), encoding="utf-8")
        self._run(*common, "task", "create", str(ok_file))
        code, listing = self._run(*common, "task", "list")
        self.assertEqual(sorted(t["task_id"] for t in listing), ["cli-a1", "cli-live"])
        self.assertEqual(self._run(*common, "pause", "cli-a1")[1]["state"], "PAUSED")
        self.assertEqual(self._run(*common, "resume", "cli-a1")[1]["state"], "NEW_TASK")
        code, _ = self._run(*common, "resume", "cli-live")
        self.assertEqual(code, 1)
        code, _ = self._run(*common, "run", "cli-a1")
        self.assertEqual(code, 1)  # fail-closed: no enabled executor -> nothing invoked
        self.assertEqual(self._run(*common, "task", "show", "cli-a1")[1]["state"], "NEW_TASK")
        code, journal = self._run(*common, "journal", "--verify")
        self.assertEqual((code, journal["journal_ok"]), (0, True))
        code, rec = self._run(*common, "recover")
        self.assertEqual(code, 0)
        self.assertTrue(all(t["replay_matches"] for t in rec["tasks"]))
        self.assertEqual(self._run(*common, "replay", "cli-a1")[1]["match"], True)
        code, status = self._run(*common, "status")
        self.assertEqual(status["tasks_by_state"], {"BLOCKED": 1, "NEW_TASK": 1})
        self.assertEqual(self._run(*common, "cancel", "cli-a1")[1]["state"], "CANCELLED")

    def test_simulate_scenarios(self):
        expected = {"happy": ("DONE", 0), "test-failure": ("DONE", 1), "review-reject": ("DONE", 1),
                    "fix-exhaustion": ("BLOCKED", 3)}
        for scenario, (state, cycles) in expected.items():
            code, out = self._run("simulate", "--scenario", scenario)
            self.assertEqual((code, out["final_state"], out["fix_cycles"], out["journal_ok"]), (0, state, cycles, True))


class ArchitectureBoundaryTests(unittest.TestCase):
    FORBIDDEN = ("MetaTrader5", "socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp", "anthropic",
                 "openai", "google", "atlas", "atlas2")

    def _imports(self, root: Path):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    yield path, [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    yield path, [node.module]

    def test_dev_workflow_has_no_broker_network_sdk_or_atlas_imports(self):
        bad = [(str(p), n) for p, names in self._imports(PKG) for n in names
               if any(n == f or n.startswith(f + ".") for f in self.FORBIDDEN)]
        self.assertEqual(bad, [])
        for path in PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("order_send", text)
            self.assertNotIn("order_check", text)

    def test_atlas2_artifact_is_not_contaminated_by_dev_workflow(self):
        for path in (ROOT / "atlas2").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in ("atlas_dev_workflow", "tools.", "claude", "codex", "gemini"):
                self.assertNotIn(token, text, f"{path} references {token}")

    def test_runtime_state_is_git_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".atlas-dev-workflow/", ignore)


if __name__ == "__main__":
    unittest.main()
