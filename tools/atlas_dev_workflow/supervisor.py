"""Development Supervisor: the only component that mutates durable task state.

Agents return packets; the supervisor validates them, applies the Owner Development Policy plus the Atlas
overlay, and commits exactly one legal transition per step under a fenced lease.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from tools.owner_dev_policy import providers as owner_providers
from tools.owner_dev_policy.checkpoint import checkpoint_due
from tools.owner_dev_policy.classification import Finding, blocks_development_done, queue_order
from tools.owner_dev_policy.compute import budget_exceeded, context_report
from tools.owner_dev_policy.done import evaluate_done
from tools.owner_dev_policy.monitoring import CONTROL_REQUEST_V1, validate_control_request
from tools.owner_dev_policy.policy import OwnerDevelopmentPolicy, owned_path_conflicts
from tools.owner_dev_policy.redaction import bounded_excerpt
from tools.owner_dev_policy.schema import SHA_RE

from . import policy, project, projections
from .contracts import HANDOFF_V1, Handoff, Packet, TaskContract, canonical_json, digest, parse_packet
from .errors import ContractError, GitSafetyError, PolicyViolation, ProviderError, ProviderExhausted, StaleLease
from .executors import AgentExecutor, Binding, extract_packet, output_digest, validate_bindings
from .gitops import MergeGateway, Workspace
from .references import query as query_references
from .roles import IMPLEMENTER, PLANNER, QA, REVIEWER, SUPERVISOR, instructions_for
from .states import ACTIVE, BLOCK_CODES_RECOVERABLE, TERMINAL, State
from .store import Store

DEFAULT_LEASE_TTL_US = 30 * 60 * 1_000_000
PRIOR_EVIDENCE_LIMIT = 6
REFERENCE_LIMIT = 8


@dataclass(frozen=True)
class StepResult:
    task_id: str
    state: str
    action: str
    waiting: bool = False
    progressed: bool = True


@dataclass(frozen=True)
class RecordedIdentity:
    """Executor identity as durably recorded (`kind:provider:model`), independent of the current config."""
    executor_id: str

    @property
    def provider(self) -> str:
        return self.executor_id.split(":")[1]


def _classification(task: Mapping[str, Any]) -> policy.Classification:
    c = json.loads(task["classification_json"])
    return policy.Classification(c["task_class"], tuple(c["impact_areas"]), tuple(c["owner_sensitive"]),
                                 tuple(c["reasons"]), c["legacy_touch"])


def _contract(task: Mapping[str, Any]) -> TaskContract:
    return TaskContract.from_dict(json.loads(task["contract_json"]))


def _block_summary(blocks: list[policy.Block]) -> tuple[str, str]:
    return blocks[0].code, "; ".join(f"{b.code}: {b.reason}" for b in blocks)


def _implementers(store: Store, task_id: str) -> list[RecordedIdentity]:
    """Every executor that produced an accepted implementation for this task (failover successors included)."""
    seen = []
    for run in store.agent_runs(task_id):
        if run["role"] == IMPLEMENTER and run["status"] == "OK" and run["executor_id"] not in seen:
            seen.append(run["executor_id"])
    return [RecordedIdentity(e) for e in seen]


def _classified_findings(review: Mapping[str, Any]) -> list[Finding]:
    found = [Finding.from_dict({"finding_id": f.get("finding_id", f"F{i}"), "classification": f["classification"],
                                "summary": f["summary"]})
             for i, f in enumerate(review.get("findings", [])) if "classification" in f]
    audit = review.get("maintainability_audit") or {}
    return found + [Finding.from_dict(f) for f in audit.get("findings", [])]


class Supervisor:
    def __init__(self, store: Store, bindings: Mapping[str, Binding], *, workspace: Workspace | None = None,
                 merge_gateway: MergeGateway | None = None, worker_id: str = "supervisor",
                 lease_ttl_us: int = DEFAULT_LEASE_TTL_US,
                 owner_policy: OwnerDevelopmentPolicy = OwnerDevelopmentPolicy(),
                 reference_index: Mapping[str, Any] | None = None):
        self.chains = validate_bindings(bindings, independence=owner_policy.reviewer_independence)
        self.store = store
        self.workspace = workspace
        self.merge_gateway = merge_gateway
        self.worker_id = worker_id
        self.lease_ttl_us = lease_ttl_us
        self.policy = owner_policy
        self.reference_index = reference_index
        self._lease: tuple[str, int] | None = None

    def intake(self, raw_contract: Mapping[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        return intake(self.store, raw_contract, actor=actor)

    # -- worker loop ------------------------------------------------------------------------------

    def run(self, task_id: str, *, max_steps: int = 100) -> StepResult:
        result = StepResult(task_id, self.store.get_task(task_id)["state"], "noop", progressed=False)
        for _ in range(max_steps):
            result = self.step(task_id)
            if result.waiting or not result.progressed:
                break
        return result

    def run_all(self, *, max_steps: int = 100) -> list[StepResult]:
        """Run runnable tasks in priority order. Priority orders the queue; it never skips a gate."""
        runnable = [{"task_id": t["task_id"], "priority": _contract(t).priority, "created_us": t["created_us"]}
                    for t in self.store.list_tasks() if State(t["state"]) in ACTIVE]
        return [self.run(t["task_id"], max_steps=max_steps) for t in queue_order(runnable)]

    def step(self, task_id: str) -> StepResult:
        task = self.store.get_task(task_id)
        state = State(task["state"])
        if state not in ACTIVE:
            return StepResult(task_id, state, "not_runnable", progressed=False)
        try:
            token = self.store.acquire_lease(task_id, self.worker_id, self.lease_ttl_us)
        except StaleLease as exc:
            return StepResult(task_id, state, f"lease_unavailable: {exc}", progressed=False)
        self._lease = (self.worker_id, token)
        try:
            task = self.store.get_task(task_id)
            if checkpoint_due(projections.last_checkpoint_us(self.store, task), self.store.clock(),
                              self.policy.checkpoint_interval_s):
                projections.record_checkpoint(self.store, task_id, "interval", actor=self.worker_id)
            result = getattr(self, f"_on_{state.value.lower()}")(task)
            if result.waiting:
                projections.record_checkpoint(self.store, task_id, "waiting", actor=self.worker_id)
            return result
        except StaleLease as exc:
            self.store.journal(task_id, "stale_worker_rejected", self.worker_id, {"token": token, "error": str(exc)})
            return StepResult(task_id, self.store.get_task(task_id)["state"], "stale_lease_rejected", progressed=False)
        finally:
            self.store.release_lease(task_id, self.worker_id, token)
            self._lease = None

    # -- transitions helpers ----------------------------------------------------------------------

    def _go(self, task: Mapping[str, Any], to: State, reason: str, *, updates: dict[str, Any] | None = None,
            evidence: dict[str, Any] | None = None, action: str | None = None) -> StepResult:
        new = self.store.transition(task["task_id"], to, actor=SUPERVISOR, reason=reason,
                                    expected_version=task["version"], lease=self._lease, updates=updates,
                                    evidence=evidence)
        return StepResult(task["task_id"], new["state"], action or reason)

    def _block(self, task: Mapping[str, Any], blocks: list[policy.Block], reason: str) -> StepResult:
        code, text = _block_summary(blocks)
        result = self._go(task, State.BLOCKED, reason, updates={"block_code": code, "block_reason": text},
                          evidence={"blocks": [b.to_dict() for b in blocks]}, action=f"blocked:{code}")
        trigger = "provider_exhausted" if code == "PROVIDER_UNAVAILABLE" else "blocked"
        projections.record_checkpoint(self.store, task["task_id"], trigger, actor=SUPERVISOR)
        return result

    def _fail(self, task: Mapping[str, Any], code: str, reason: str) -> StepResult:
        result = self._go(task, State.FAILED, reason, updates={"block_code": code, "block_reason": reason},
                          action=f"failed:{code}")
        projections.record_checkpoint(self.store, task["task_id"], "terminal", actor=SUPERVISOR)
        return result

    def _enter_fixing(self, task: Mapping[str, Any], reason: str, evidence: dict[str, Any]) -> StepResult:
        if task["fix_cycles"] >= task["max_fix_cycles"]:
            return self._block(task, [policy.Block("FIX_CYCLES_EXHAUSTED",
                                                   f"{task['fix_cycles']}/{task['max_fix_cycles']} fix cycles used; {reason}")],
                               "fix cycle budget exhausted")
        return self._go(task, State.FIXING, reason, updates={"fix_cycles": task["fix_cycles"] + 1}, evidence=evidence)

    # -- agent invocation -------------------------------------------------------------------------

    def _step_key(self, task: Mapping[str, Any], role: str, kind: str) -> str:
        return "step_" + digest("atlas-devwf.step.v1", {
            "task_id": task["task_id"], "state": task["state"], "version": task["version"], "role": role,
            "kind": kind, "fix_cycles": task["fix_cycles"]})[:40]

    def _prior_evidence(self, task: Mapping[str, Any], role: str) -> tuple[tuple[dict[str, Any], ...], int]:
        """Recent QA/review evidence (bounded; the omitted count is reported, never silently dropped)."""
        qualifying = [r for r in self.store.agent_runs(task["task_id"]) if r["status"] == "OK" and r["role"] in (QA, REVIEWER)]
        kept = qualifying[-PRIOR_EVIDENCE_LIMIT:]
        out = []
        for run in kept:
            p = json.loads(run["packet_json"])["payload"]
            out.append({"role": run["role"], "verdict": p.get("verdict"), "checks": p.get("checks"),
                        "findings": p.get("findings"), "head_sha": p.get("head_sha")})
        if role == PLANNER:
            for e in self.store.journal_entries(task["task_id"]):
                if e["event_type"] == "external_research":
                    out.append({"role": "external_research", "authority": "none", **e["payload"]})
        return tuple(out), len(qualifying) - len(kept)

    def _references(self, task: Mapping[str, Any], contract: TaskContract,
                    cls: policy.Classification) -> tuple[tuple[dict[str, Any], ...], int]:
        if not self.reference_index:
            return (), 0
        text = " ".join([contract.title, contract.objective, *contract.scope_paths, *cls.impact_areas])
        hits = query_references(self.reference_index, text, include_legacy=cls.legacy_touch,
                                limit=len(self.reference_index.get("entries", [])) or 1)
        kept = tuple({k: h[k] for k in ("ref_id", "kind", "path", "sha256", "title")} for h in hits[:REFERENCE_LIMIT])
        return kept, len(hits) - len(kept)

    def _handoff(self, task: Mapping[str, Any], role: str, kind: str, step_key: str,
                 expected_head: str | None) -> Handoff:
        contract, cls = _contract(task), _classification(task)
        prior, prior_omitted = self._prior_evidence(task, role)
        refs, refs_omitted = self._references(task, contract, cls)
        return Handoff(
            task_id=task["task_id"], role=role, state=task["state"], step_key=step_key,
            contract_digest=task["contract_digest"], task_class=cls.task_class, expected_kind=kind,
            instructions=instructions_for(role, kind), contract=contract.to_dict(),
            required_checks=policy.required_checks(cls, contract) if role == QA else (),
            expected_head=expected_head, fix_cycle=task["fix_cycles"], prior_evidence=prior, references=refs,
            project_id=project.PROJECT_ID, priority=contract.priority,
            effort=project.effort_for(cls.task_class, architecture_significant=contract.architecture_significant,
                                      override=contract.effort_override),
            context=context_report(prior_evidence=prior_omitted, references=refs_omitted))

    def _call_agent(self, task: Mapping[str, Any], role: str, kind: str, *, expected_head: str | None = None,
                    chain: list[AgentExecutor] | None = None) -> Packet | policy.Block:
        """Invoke a role through its failover chain; replay a recorded packet instead of re-invoking.

        Transient errors retry on the same executor within the owner-policy bound. Exhaustion (usage, auth,
        rate limit) or exhausted retries write a durable checkpoint and hand the identical handoff to the
        next qualified executor. Invalid output never fails over: it is a defect, not an outage.
        """
        task_id = task["task_id"]
        step_key = self._step_key(task, role, kind)
        recorded = self.store.get_agent_run(step_key)
        if recorded is not None:
            self.store.journal(task_id, "agent_replayed", SUPERVISOR, {"step_key": step_key, "status": recorded["status"]})
            if recorded["status"] == "OK":
                raw = json.loads(recorded["packet_json"])
                return Packet(role, raw["kind"], raw["task_id"], raw["step_key"], raw["payload"])
            return self._agent_failure_block(recorded["status"], recorded["output_excerpt"] or "")
        contract = _contract(task)
        exceeded = budget_exceeded(contract.budget, projections.usage_totals(self.store.journal_entries(task_id)))
        if exceeded:
            return policy.Block("BUDGET_EXCEEDED", f"task budget {exceeded} reached before the {role} step")
        handoff = self._handoff(task, role, kind, step_key, expected_head)
        payload = handoff.to_dict() | {"workdir": task["worktree_path"]}
        chain = chain if chain is not None else self.chains[role]
        status, error, text, attempts, executor = "PROVIDER_ERROR", "", "", 0, chain[0]
        for index, executor in enumerate(chain):
            if index:
                self._failover(task_id, role, step_key, chain[index - 1], executor, error, payload)
            for _ in range(self.policy.max_provider_retries + 1):
                attempts += 1
                exhausted = False
                self.store.check_lease(task_id, *self._lease)
                try:
                    result = executor.run(payload)
                    text = result.text
                    if result.truncated:
                        raise ContractError("agent output was truncated; truncated output is never treated as complete")
                    packet = parse_packet(extract_packet(text), role=role, expected_kind=kind, task_id=task_id,
                                          step_key=step_key)
                except ProviderError as exc:
                    status, error, exhausted = "PROVIDER_ERROR", str(exc), isinstance(exc, ProviderExhausted)
                except ContractError as exc:
                    status, error = "INVALID_OUTPUT", str(exc)
                else:
                    self.store.record_agent_run(
                        step_key=step_key, task_id=task_id, role=role, executor_id=executor.executor_id,
                        attempts=attempts, status="OK", packet=packet.to_dict(), output_digest=output_digest(text),
                        output_excerpt=bounded_excerpt(text), lease=self._lease,
                        telemetry={"usage": result.usage, "effort": handoff.effort, "context": handoff.context,
                                   "context_truncated": handoff.context["truncated"]})
                    return packet
                self.store.journal(task_id, "agent_attempt_failed", SUPERVISOR,
                                   {"step_key": step_key, "attempt": attempts, "executor_id": executor.executor_id,
                                    "status": status, "error": bounded_excerpt(error)})
                if exhausted:
                    break  # no same-executor retry after usage/auth/rate-limit exhaustion
            if status == "INVALID_OUTPUT":
                break
        excerpt = bounded_excerpt(f"{error}\n{text}")
        self.store.record_agent_run(step_key=step_key, task_id=task_id, role=role, executor_id=executor.executor_id,
                                    attempts=attempts, status=status, packet=None,
                                    output_digest=output_digest(text) if text else None, output_excerpt=excerpt,
                                    lease=self._lease)
        return self._agent_failure_block(status, excerpt)

    def _failover(self, task_id: str, role: str, step_key: str, failed: AgentExecutor, successor: AgentExecutor,
                  error: str, payload: Mapping[str, Any]) -> None:
        """Durable checkpoint, then a recorded handoff; the successor receives the identical handoff."""
        projections.record_checkpoint(self.store, task_id, "provider_exhausted", actor=SUPERVISOR,
                                      executor=failed.executor_id)
        self.store.journal(task_id, "provider_failover", SUPERVISOR, {
            "step_key": step_key, "role": role, "from_executor": failed.executor_id,
            "to_executor": successor.executor_id, "reason": bounded_excerpt(error),
            "handoff_digest": digest(HANDOFF_V1, dict(payload))})

    @staticmethod
    def _agent_failure_block(status: str, detail: str) -> policy.Block:
        if status == "PROVIDER_ERROR":
            return policy.Block("PROVIDER_UNAVAILABLE", f"provider chain exhausted: {detail[:300]}", recoverable=True)
        return policy.Block("INVALID_AGENT_OUTPUT", f"structured output invalid after retries: {detail[:300]}")

    def _agent_or_stop(self, task: Mapping[str, Any], outcome: Packet | policy.Block) -> StepResult | None:
        if isinstance(outcome, Packet):
            return None
        if outcome.code == "INVALID_AGENT_OUTPUT":
            return self._fail(task, outcome.code, outcome.reason)
        return self._block(task, [outcome], "agent unavailable" if outcome.recoverable else "owner policy gate")

    def _head_mismatch(self, task: Mapping[str, Any], reported: str, expected: str | None, who: str) -> StepResult | None:
        if expected is not None and reported != expected:
            return self._block(task, [policy.Block("HEAD_MISMATCH", f"{who} reported head {reported}, expected {expected}")],
                               "exact head tracking")
        return None

    # -- state handlers ---------------------------------------------------------------------------

    def _on_new_task(self, task: Mapping[str, Any]) -> StepResult:
        return self._go(task, State.PLANNING, "intake accepted; planning")

    def _on_planning(self, task: Mapping[str, Any]) -> StepResult:
        outcome = self._call_agent(task, PLANNER, "plan")
        if (stop := self._agent_or_stop(task, outcome)) is not None:
            return stop
        contract, cls = _contract(task), _classification(task)
        updated, blocks = policy.plan_blocks(contract, cls, outcome.payload)
        evidence = {"plan_step": outcome.step_key, "classification": updated.to_dict(),
                    "required_checks": list(policy.required_checks(updated, contract)),
                    "approval_categories": list(policy.approval_categories(updated))}
        if blocks:
            return self._block(task, blocks, "plan policy gate")
        return self._go(task, State.READY, "plan accepted",
                        updates={"task_class": updated.task_class,
                                 "classification_json": canonical_json(updated.to_dict())}, evidence=evidence)

    def _on_ready(self, task: Mapping[str, Any]) -> StepResult:
        if self.workspace is None:
            return self._go(task, State.IMPLEMENTING, "no workspace bound; implementer works in-place",
                            updates={"head_sha": task["base_sha"]})
        key = "wt_" + digest("atlas-devwf.worktree.v1", [task["task_id"], task["branch"], task["base_sha"]])[:32]
        request = {"task_id": task["task_id"], "branch": task["branch"], "base_sha": task["base_sha"]}
        if self.store.get_mutation(key) is None:
            projections.record_checkpoint(self.store, task["task_id"], "risky_command", actor=SUPERVISOR)
        m = self.store.begin_mutation(key, task_id=task["task_id"], kind="create_worktree", request=request,
                                      actor=SUPERVISOR)
        if m["status"] == "DONE":
            result = json.loads(m["result_json"])
        else:
            try:
                result = self.workspace.create(task["task_id"], task["branch"], task["base_sha"])
            except GitSafetyError as exc:
                self.store.finish_mutation(key, status="FAILED", result={"error": str(exc)}, actor=SUPERVISOR)
                return self._block(task, [policy.Block("GIT_UNSAFE_TARGET", str(exc))], "worktree refused")
            self.store.finish_mutation(key, status="DONE", result=result, actor=SUPERVISOR)
        return self._go(task, State.IMPLEMENTING, "task worktree ready",
                        updates={"worktree_path": result["path"], "head_sha": result["head"]}, evidence=result)

    def _implementation(self, task: Mapping[str, Any]) -> StepResult:
        outcome = self._call_agent(task, IMPLEMENTER, "implementation", expected_head=task["head_sha"])
        if (stop := self._agent_or_stop(task, outcome)) is not None:
            return stop
        p = outcome.payload
        files = set(p["files_changed"])
        if self.workspace is not None and task["worktree_path"]:
            actual = self.workspace.head(task["worktree_path"])
            if (stop := self._head_mismatch(task, p["head_sha"], actual, "implementer")) is not None:
                return stop
            if self.workspace.is_dirty(task["worktree_path"]):
                return self._block(task, [policy.Block("UNCOMMITTED_CHANGES", "task worktree is dirty after implementation")],
                                   "implementation must be committed")
            changed = getattr(self.workspace, "changed_files", None)
            if changed is not None:
                files |= set(changed(task["base_sha"], actual))  # do not trust the agent's file list alone
        contract, cls = _contract(task), _classification(task)
        checked = dict(p, files_changed=sorted(files))
        blocks = policy.implementation_blocks(contract, cls, checked)
        evidence = {"implementation_step": outcome.step_key, "head_sha": p["head_sha"], "files_changed": sorted(files),
                    "finding_dispositions": p.get("finding_dispositions", [])}
        if blocks:
            return self._block(task, blocks, "implementation policy gate")
        return self._go(task, State.TESTING, "implementation recorded", updates={"head_sha": p["head_sha"]},
                        evidence=evidence)

    _on_implementing = _implementation
    _on_fixing = _implementation

    def _on_testing(self, task: Mapping[str, Any]) -> StepResult:
        outcome = self._call_agent(task, QA, "qa_report", expected_head=task["head_sha"])
        if (stop := self._agent_or_stop(task, outcome)) is not None:
            return stop
        if (stop := self._head_mismatch(task, outcome.payload["head_sha"], task["head_sha"], "qa")) is not None:
            return stop
        required = policy.required_checks(_classification(task), _contract(task))
        qa = policy.evaluate_qa(required, outcome.payload)
        evidence = {"qa_step": outcome.step_key, "verdict": outcome.payload["verdict"], "required_checks": list(required),
                    "missing_checks": list(qa.missing_checks), "failed_checks": list(qa.failed_checks),
                    "blockers": list(qa.blockers), "notes": list(qa.notes), "tests": outcome.payload["tests"]}
        if qa.blockers:
            return self._block(task, [policy.Block("EVIDENCE_BLOCKER", f"automatic blocker flags: {list(qa.blockers)}")],
                               "QA evidence blocker")
        if qa.passed:
            return self._go(task, State.REVIEW, "QA passed", evidence=evidence)
        return self._enter_fixing(task, "QA failed or evidence insufficient", evidence)

    def _on_review(self, task: Mapping[str, Any]) -> StepResult:
        implementers = _implementers(self.store, task["task_id"])
        reviewers = owner_providers.independent_reviewers(self.chains[REVIEWER], implementers,
                                                          self.policy.reviewer_independence)
        if not reviewers:
            return self._block(task, [policy.Block(
                "REVIEWER_NOT_INDEPENDENT", f"no configured reviewer is independent ({self.policy.reviewer_independence}) "
                f"from implementers {[i.executor_id for i in implementers]}")], "independent review unavailable")
        outcome = self._call_agent(task, REVIEWER, "review", expected_head=task["head_sha"], chain=reviewers)
        if (stop := self._agent_or_stop(task, outcome)) is not None:
            return stop
        if (stop := self._head_mismatch(task, outcome.payload["head_sha"], task["head_sha"], "reviewer")) is not None:
            return stop
        review = outcome.payload
        blockers = policy.review_blockers(review)
        classified = _classified_findings(review)
        must_fix = [f.to_dict() for f in classified if blocks_development_done(f)]
        contract = _contract(task)
        audit = review.get("maintainability_audit")
        audit_ok = not contract.architecture_significant or bool(audit and audit["passed"])
        evidence = {"review_step": outcome.step_key, "verdict": review["verdict"], "findings": review["findings"],
                    "classified_findings": [f.to_dict() for f in classified], "blockers": list(blockers),
                    "maintainability_audit": audit,
                    "reviewer_executor": self.store.get_agent_run(outcome.step_key)["executor_id"],
                    "implementer_executors": [i.executor_id for i in implementers]}
        if blockers:
            return self._block(task, [policy.Block("EVIDENCE_BLOCKER", f"reviewer flagged blockers: {list(blockers)}")],
                               "review evidence blocker")
        if review["verdict"] == "APPROVE" and not must_fix and audit_ok:
            return self._go(task, State.APPROVAL, "independent review approved", evidence=evidence)
        reason = ("reviewer requested changes" if review["verdict"] != "APPROVE" else
                  "approval inconsistent with open MUST_FIX_BEFORE_IMPLEMENTATION findings" if must_fix else
                  "architecture-significant change lacks a passed maintainability audit")
        return self._enter_fixing(task, reason, evidence)

    def _on_approval(self, task: Mapping[str, Any]) -> StepResult:
        cls = _classification(task)
        categories = list(policy.approval_categories(cls))
        if not categories:
            return self._go(task, State.MERGE, "approval gate: not owner-sensitive (auto)",
                            updates={"approved_head_sha": task["head_sha"]},
                            evidence={"approval": "AUTO_NOT_OWNER_SENSITIVE", "activation_allowed": False})
        approval_id = "apr_" + digest("atlas-devwf.approval.v1", [task["task_id"], task["head_sha"]])[:32]
        approval = self.store.open_approval(approval_id=approval_id, task_id=task["task_id"],
                                            head_sha=task["head_sha"], categories=categories, actor=SUPERVISOR)
        if approval["status"] == "PENDING":
            return StepResult(task["task_id"], task["state"], f"awaiting_owner_approval:{approval_id}", waiting=True,
                              progressed=False)
        if approval["status"] == "REJECTED":
            return self._block(task, [policy.Block("OWNER_REJECTED", approval["decision_note"] or "owner rejected")],
                               "owner rejected")
        if approval["head_sha"] != task["head_sha"]:
            raise PolicyViolation("approval bound to a different head")
        return self._go(task, State.MERGE, "owner approved exact head", updates={"approved_head_sha": task["head_sha"]},
                        evidence={"approval_id": approval_id, "categories": categories, "activation_allowed": False})

    def _merge_key(self, task: Mapping[str, Any]) -> str:
        contract = _contract(task)
        return "mrg_" + digest("atlas-devwf.merge.v1", [task["task_id"], task["approved_head_sha"],
                                                         contract.target_branch])[:32]

    def _on_merge(self, task: Mapping[str, Any]) -> StepResult:
        if self.merge_gateway is None:
            return StepResult(task["task_id"], task["state"], "no_merge_gateway_bound", waiting=True, progressed=False)
        contract = _contract(task)
        key = self._merge_key(task)
        request = {"task_id": task["task_id"], "branch": task["branch"], "target": contract.target_branch,
                   "head_sha": task["approved_head_sha"], "method": "pull_request"}
        if self.store.get_mutation(key) is None:
            projections.record_checkpoint(self.store, task["task_id"], "risky_command", actor=SUPERVISOR)
        m = self.store.begin_mutation(key, task_id=task["task_id"], kind="merge_request", request=request,
                                      actor=SUPERVISOR)
        result = json.loads(m["result_json"]) if m["status"] == "DONE" else self.merge_gateway.lookup(key)
        if result is None and m["status"] == "PENDING":
            # Gateways must be idempotent by key; PENDING means the request may not have been sent.
            sent = self.merge_gateway.request_merge(key=key, task_id=task["task_id"], branch=task["branch"],
                                                    target=contract.target_branch, head_sha=task["approved_head_sha"])
            if sent.get("status") == "MERGED":
                result = sent
            else:
                self.store.finish_mutation(key, status="REQUESTED", result=sent, actor=SUPERVISOR)
        if result is None or result.get("status") != "MERGED":
            return StepResult(task["task_id"], task["state"], f"awaiting_merge:{key}", waiting=True, progressed=False)
        if m["status"] != "DONE":
            self.store.finish_mutation(key, status="DONE", result=result, actor=SUPERVISOR)
        if result["source_head"] != task["approved_head_sha"]:
            return self._block(task, [policy.Block("MERGE_HEAD_MISMATCH",
                                                   f"merged {result['source_head']} != approved {task['approved_head_sha']}")],
                               "merge head mismatch")
        return self._go(task, State.VERIFY, "merge recorded (merge is not activation)",
                        evidence={"merge": result, "idempotency_key": key, "activation": "NOT_ACTIVATED"})

    def _on_verify(self, task: Mapping[str, Any]) -> StepResult:
        merge = json.loads(self.store.get_mutation(self._merge_key(task))["result_json"])
        outcome = self._call_agent(task, QA, "verify_report", expected_head=merge["merged_head"])
        if (stop := self._agent_or_stop(task, outcome)) is not None:
            return stop
        if (stop := self._head_mismatch(task, outcome.payload["head_sha"], merge["merged_head"], "verify")) is not None:
            return stop
        contract = _contract(task)
        required = policy.required_checks(_classification(task), contract)
        qa = policy.evaluate_qa(required, outcome.payload)
        if qa.blockers:
            return self._block(task, [policy.Block("EVIDENCE_BLOCKER", f"post-merge blockers: {list(qa.blockers)}")],
                               "verify evidence blocker")
        if not qa.passed:
            return self._fail(task, "VERIFY_FAILED", f"post-merge verification failed; missing={list(qa.missing_checks)} "
                                                     f"failed={list(qa.failed_checks)}")
        boundary = policy.boundary_statement(contract)
        dod = self._definition_of_done(task, qa_passed=qa.passed, merge=merge, boundary=boundary)
        if not dod["decision"]["done"]:
            return self._block(task, [policy.Block("DEFINITION_OF_DONE_NOT_MET", f"failed: {dod['decision']['failed']}")],
                               "definition of done")
        return self._go(task, State.DONE, "verified; development task complete (not strategy promotion)",
                        evidence={"verify_step": outcome.step_key, "merged_head": merge["merged_head"],
                                  "boundary": boundary, "definition_of_done": dod})

    def _definition_of_done(self, task: Mapping[str, Any], *, qa_passed: bool, merge: Mapping[str, Any],
                            boundary: Mapping[str, Any]) -> dict[str, Any]:
        """Owner DoD composed with the Atlas DoD; the Atlas overlay can only add requirements.

        Writes the final pre-DONE checkpoint first, so `checkpoint_recorded` proves a durable checkpoint exists
        for the exact approved head in VERIFY.
        """
        task_id = task["task_id"]
        contract = _contract(task)
        _, review = projections.last_evidence(self.store.journal_entries(task_id), "review_step")
        reviewer = review.get("reviewer_executor")
        implementers = _implementers(self.store, task_id)
        independent = reviewer is not None and owner_providers.independent(
            RecordedIdentity(reviewer), implementers, self.policy.reviewer_independence)
        projections.record_checkpoint(self.store, task_id, "terminal", actor=SUPERVISOR)
        cp = projections.last_entry(self.store.journal_entries(task_id), "checkpoint")
        replay = self.store.replay_state(task_id)
        current = self.store.get_task(task_id)
        owner = {
            "qualification_passed": qa_passed,
            "independent_review_passed": independent and review.get("verdict") == "APPROVE",
            "checkpoint_recorded": cp is not None and cp["payload"]["head_sha"] == task["approved_head_sha"]
            and cp["payload"]["state"] == State.VERIFY.value,
            "no_open_must_fix_before_implementation": not any(
                blocks_development_done(Finding.from_dict(f)) for f in review.get("classified_findings", [])),
            "integration_state_known": bool(SHA_RE.fullmatch(str(merge.get("merged_head")))),
            "journal_reconstructable": self.store.verify_journal()[0]
            and (replay["state"], replay["version"]) == (current["state"], current["version"]),
            "maintainability_audit_passed": not contract.architecture_significant
            or bool((review.get("maintainability_audit") or {}).get("passed")),
        }
        atlas = {
            "atlas_post_merge_verification_passed": qa_passed,
            "atlas_no_activation_or_promotion": boundary["activation_allowed"] is False
            and boundary["merge_is_activation"] is False and boundary["strategy_promoted"] is False,
        }
        decision = evaluate_done(owner, atlas)
        return {"owner": owner, "project": atlas, "decision": {"done": decision.done, "failed": list(decision.failed)}}


# -- operator commands (no agent involvement; always revoke outstanding leases) --------------------

def _holds_lane(task: Mapping[str, Any]) -> bool:
    """A task owns its paths while it can still progress: not terminal and not irrecoverably BLOCKED."""
    state = State(task["state"])
    if state is State.BLOCKED:
        return task["block_code"] in BLOCK_CODES_RECOVERABLE
    return state not in TERMINAL


def intake(store: Store, raw_contract: Mapping[str, Any], *, actor: str = "operator") -> dict[str, Any]:
    """Validate, classify and register a TaskContract; fail-closed policy blocks happen before any agent call."""
    contract = TaskContract.from_dict(raw_contract)
    cls = policy.classify(contract)
    task = store.create_task(task_id=contract.task_id, contract=contract.to_dict(), contract_digest=contract.digest,
                             classification=cls.to_dict(), branch=contract.work_branch, base_sha=contract.base_sha,
                             max_fix_cycles=contract.max_fix_cycles, actor=actor)
    if task["version"] != 0 or task["state"] != State.NEW_TASK:
        return task  # identical re-intake is idempotent
    blocks = policy.intake_blocks(contract, cls)
    lanes = {t["task_id"]: json.loads(t["contract_json"])["scope_paths"] for t in store.list_tasks()
             if t["task_id"] != contract.task_id and _holds_lane(t)}
    if conflicts := owned_path_conflicts(contract.scope_paths, lanes):
        blocks.append(policy.Block("OWNED_PATHS_CONFLICT", f"owned paths already owned by active task lanes: {conflicts}"))
    store.journal(contract.task_id, "policy_evaluated", SUPERVISOR, {
        "stage": "intake", "classification": cls.to_dict(),
        "required_checks": list(policy.required_checks(cls, contract)),
        "experiment_required": policy.experiment_required(cls),
        "approval_categories": list(policy.approval_categories(cls)),
        "priority": contract.priority, "blocks": [b.to_dict() for b in blocks],
        "boundary": policy.boundary_statement(contract)})
    if blocks:
        code, reason = _block_summary(blocks)
        task = store.transition(contract.task_id, State.BLOCKED, actor=SUPERVISOR, reason="intake policy gate",
                                expected_version=0, updates={"block_code": code, "block_reason": reason},
                                evidence={"blocks": [b.to_dict() for b in blocks]})
    return task


def pause(store: Store, task_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    t = store.get_task(task_id)
    if State(t["state"]) not in ACTIVE:
        raise PolicyViolation(f"cannot pause task in {t['state']}")
    task = store.transition(task_id, State.PAUSED, actor=actor, reason=reason, expected_version=t["version"])
    projections.record_checkpoint(store, task_id, "stop", actor=actor)
    return task


def resume(store: Store, task_id: str, *, actor: str, reason: str = "operator resume") -> dict[str, Any]:
    t = store.get_task(task_id)
    if t["state"] == State.BLOCKED and t["block_code"] not in BLOCK_CODES_RECOVERABLE:
        raise PolicyViolation(f"BLOCKED({t['block_code']}) is not recoverable by resume; cancel or open a new task")
    if t["state"] not in (State.PAUSED, State.BLOCKED):
        raise PolicyViolation(f"cannot resume task in {t['state']}")
    return store.transition(task_id, State(t["origin_state"]), actor=actor, reason=reason,
                            expected_version=t["version"])


def cancel(store: Store, task_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    t = store.get_task(task_id)
    if State(t["state"]) in TERMINAL:
        raise PolicyViolation(f"task already terminal ({t['state']})")
    task = store.transition(task_id, State.CANCELLED, actor=actor, reason=reason, expected_version=t["version"])
    projections.record_checkpoint(store, task_id, "stop", actor=actor)
    return task


def decide(store: Store, approval_id: str, *, approve: bool, actor: str, note: str = "",
           activation_allowed: bool = False) -> dict[str, Any]:
    if activation_allowed:
        store.journal(store.get_approval(approval_id)["task_id"], "activation_request_rejected", actor,
                      {"approval_id": approval_id, "reason": "activation_allowed=true is always rejected"})
        raise PolicyViolation("activation_allowed=true is always rejected by this adapter")
    return store.decide_approval(approval_id, approve=approve, decided_by=actor, note=note)


def add_external_research(store: Store, task_id: str, *, actor: str, source: str, text: str) -> int:
    """Auxiliary research lane: untrusted evidence for the Planner only, never code-mutation or promotion authority."""
    store.get_task(task_id)
    return store.journal(task_id, "external_research", actor, {
        "source": source, "authority": "none", "trust": "untrusted_until_independent_review",
        "digest": output_digest(text), "excerpt": bounded_excerpt(text)})


def apply_control(store: Store, raw_request: Mapping[str, Any], *,
                  authority: Mapping[str, list[str]] = project.DEFAULT_CONTROL_AUTHORITY) -> dict[str, Any]:
    """Enforce an abstract control request (e.g. from the Command Center) under Atlas's own authority table.

    The channel a request arrives on grants nothing: only `requested_by` listed for the action in Atlas's
    authority table may exercise it. Every decision is journaled; a repeated request_id is not re-applied.
    """
    req = validate_control_request(raw_request)
    if req["project_id"] != project.PROJECT_ID:
        raise PolicyViolation(f"control request for project {req['project_id']!r} refused by {project.PROJECT_ID}")
    task_id = store.get_approval(req["target"])["task_id"] if req["action"] in ("approve", "reject") else req["target"]
    store.get_task(task_id)
    for e in store.journal_entries(task_id):
        if e["event_type"] == "control_request" and e["payload"]["request_id"] == req["request_id"]:
            if e["payload"]["request_digest"] != digest(CONTROL_REQUEST_V1, req):
                raise PolicyViolation(f"control request_id {req['request_id']} reused with different content")
            return {"request_id": req["request_id"], "accepted": e["payload"]["accepted"], "replayed": True,
                    "detail": e["payload"]["detail"]}
    record = {"request_id": req["request_id"], "action": req["action"], "target": req["target"],
              "requested_by": req["requested_by"], "channel": req["channel"], "request_digest": digest(CONTROL_REQUEST_V1, req)}
    if req["requested_by"] not in authority.get(req["action"], []):
        detail = f"{req['requested_by']!r} is not authorized for {req['action']} by the Atlas authority table"
        store.journal(task_id, "control_request", req["requested_by"], record | {"accepted": False, "detail": detail})
        raise PolicyViolation(detail)
    actor, reason = req["requested_by"], req["reason"] or f"{req['action']} via {req['channel']}"
    if req["action"] == "pause":
        pause(store, task_id, actor=actor, reason=reason)
    elif req["action"] == "resume":
        resume(store, task_id, actor=actor, reason=reason)
    elif req["action"] == "cancel":
        cancel(store, task_id, actor=actor, reason=reason)
    elif req["action"] in ("approve", "reject"):
        decide(store, req["target"], approve=req["action"] == "approve", actor=actor, note=reason)
    else:  # recover: integrity check only; resuming work is a separate supervisor run
        ok, _ = store.verify_journal()
        replay, t = store.replay_state(task_id), store.get_task(task_id)
        if not ok or (replay["state"], replay["version"]) != (t["state"], t["version"]):
            detail = "journal verification or replay mismatch; manual investigation required"
            store.journal(task_id, "control_request", actor, record | {"accepted": False, "detail": detail})
            raise PolicyViolation(detail)
    detail = f"{req['action']} applied; state now {store.get_task(task_id)['state']}"
    store.journal(task_id, "control_request", actor, record | {"accepted": True, "detail": detail})
    return {"request_id": req["request_id"], "accepted": True, "replayed": False, "detail": detail}
