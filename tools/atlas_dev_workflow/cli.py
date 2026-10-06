"""Operator CLI: `python3 -m tools.atlas_dev_workflow <command>` (JSON output for later monitoring)."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from tools.owner_dev_policy.events import append_jsonl
from tools.owner_dev_policy.glossary import lookup
from tools.owner_dev_policy.policy import OwnerDevelopmentPolicy
from tools.owner_dev_policy.schema import OwnerPolicyError

from . import RUNTIME_VERSION, policy, project, projections, simulation
from .config import Layout, default_config, load_config, repo_root, resolve_layout, write_config
from .contracts import TaskContract
from .errors import DevWorkflowError
from .executors import build_chains, discover_clis, validate_bindings
from .gitops import FakeMergeGateway, ManualMergeGateway, WorktreeManager
from .references import build_index, load_index, query, save_index
from .roles import PROFILES
from .store import SCHEMA_VERSION, Store
from .supervisor import (Supervisor, add_external_research, apply_control, cancel, decide, intake, pause,
                         resume)

SAFE_TASK_FIELDS = ("task_id", "state", "task_class", "origin_state", "block_code", "block_reason", "fix_cycles",
                    "max_fix_cycles", "branch", "worktree_path", "base_sha", "head_sha", "approved_head_sha",
                    "version", "lease_owner", "lease_token", "contract_digest")


def _out(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _task_view(t: dict[str, Any]) -> dict[str, Any]:
    view = {k: t[k] for k in SAFE_TASK_FIELDS}
    view["classification"] = json.loads(t["classification_json"])
    return view


class Ctx:
    def __init__(self, args: argparse.Namespace):
        self.root = Path(args.repo).resolve() if args.repo else repo_root()
        self.layout: Layout = resolve_layout(args.state_dir, self.root)
        self._store: Store | None = None

    @property
    def store(self) -> Store:
        if self._store is None:
            if not self.layout.db.exists():
                raise DevWorkflowError(f"no state DB at {self.layout.db}; run `init` first")
            self._store = Store(self.layout.db)
        return self._store

    def config(self) -> dict[str, Any]:
        return load_config(self.layout)

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def owner_policy(self) -> OwnerDevelopmentPolicy:
        return OwnerDevelopmentPolicy.from_dict(self.config()["owner_policy"])

    def supervisor(self) -> Supervisor:
        cfg = self.config()
        index = load_index(self.layout.references) if self.layout.references.exists() else None
        return Supervisor(self.store, build_chains(cfg),
                          workspace=WorktreeManager(cfg["repo_root"], cfg["worktrees_root"]),
                          merge_gateway=ManualMergeGateway(self.layout.merge_requests),
                          worker_id=f"worker:{Path(cfg['repo_root']).name}",
                          lease_ttl_us=int(cfg["lease_ttl_s"]) * 1_000_000,
                          owner_policy=self.owner_policy(), reference_index=index)


def cmd_init(ctx: Ctx, args: argparse.Namespace) -> None:
    ctx.layout.state_dir.mkdir(parents=True, exist_ok=True)
    created = not ctx.layout.config.exists()
    if created:
        write_config(ctx.layout, default_config(ctx.root))
    store = Store(ctx.layout.db)
    version = store.schema_version()
    store.close()
    _out({"runtime_version": RUNTIME_VERSION, "state_dir": str(ctx.layout.state_dir), "db": str(ctx.layout.db),
          "schema_version": version, "config_created": created,
          "discovered_clis": discover_clis(probe_version=args.probe_versions)})


def cmd_status(ctx: Ctx, args: argparse.Namespace) -> None:
    tasks = ctx.store.list_tasks()
    ok, tip = ctx.store.verify_journal()
    _out({"runtime_version": RUNTIME_VERSION, "state_dir": str(ctx.layout.state_dir),
          "schema_version": ctx.store.schema_version(), "runtime_schema_version": SCHEMA_VERSION,
          "tasks_by_state": dict(Counter(t["state"] for t in tasks)),
          "pending_approvals": [a["approval_id"] for a in ctx.store.approvals(status="PENDING")],
          "journal_ok": ok, "journal_tip": tip})


def cmd_discover(ctx: Ctx, args: argparse.Namespace) -> None:
    _out(discover_clis(probe_version=args.probe_versions))


def cmd_validate(ctx: Ctx, args: argparse.Namespace) -> None:
    report: dict[str, Any] = {"roles": {r: {"title": PROFILES[r].title, "packet_kinds": list(PROFILES[r].packet_kinds),
                                            "mutation_authority": PROFILES[r].mutation_authority}
                                        for r in PROFILES}}
    cfg = ctx.config()
    report["owner_policy"] = ctx.owner_policy().to_dict()
    report["role_chains"] = cfg["role_chains"]
    try:
        chains = validate_bindings(build_chains(cfg), independence=ctx.owner_policy().reviewer_independence)
        report["bindings"] = {r: [e.executor_id for e in chain] for r, chain in chains.items()}
        report["bindings_ok"] = True
    except OwnerPolicyError as exc:
        report["bindings_ok"], report["bindings_error"] = False, str(exc)
    if args.contract:
        c = TaskContract.from_dict(json.loads(Path(args.contract).read_text(encoding="utf-8")))
        cls = policy.classify(c)
        report["contract"] = {"task_id": c.task_id, "digest": c.digest, "classification": cls.to_dict(),
                              "priority": c.priority,
                              "required_checks": list(policy.required_checks(cls, c)),
                              "approval_categories": list(policy.approval_categories(cls)),
                              "intake_blocks": [b.to_dict() for b in policy.intake_blocks(c, cls)]}
    _out(report)


def cmd_task(ctx: Ctx, args: argparse.Namespace) -> None:
    if args.task_cmd == "create":
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        _out(_task_view(intake(ctx.store, raw, actor=args.actor)))
    elif args.task_cmd == "list":
        _out([{k: t[k] for k in ("task_id", "state", "task_class", "block_code", "fix_cycles")}
              for t in ctx.store.list_tasks()])
    else:
        t = ctx.store.get_task(args.task_id)
        _out(_task_view(t) | {"contract": json.loads(t["contract_json"]),
                              "approvals": ctx.store.approvals(task_id=args.task_id),
                              "mutations": ctx.store.mutations(args.task_id)})


def cmd_run(ctx: Ctx, args: argparse.Namespace) -> None:
    sup = ctx.supervisor()
    if args.task_id:
        r = sup.run(args.task_id, max_steps=args.max_steps)
        _out({"task_id": r.task_id, "state": r.state, "last_action": r.action, "waiting": r.waiting})
    else:
        _out([{"task_id": r.task_id, "state": r.state, "last_action": r.action, "waiting": r.waiting}
              for r in sup.run_all(max_steps=args.max_steps)])


def cmd_journal(ctx: Ctx, args: argparse.Namespace) -> None:
    if args.verify:
        ok, tip = ctx.store.verify_journal()
        _out({"journal_ok": ok, "detail": tip})
        if not ok:
            sys.exit(2)
        return
    entries = ctx.store.journal_entries(args.task_id)
    _out([{k: e[k] for k in ("seq", "event_type", "from_state", "to_state", "actor", "created_us", "entry_hash")}
          | {"payload": e["payload"]} for e in entries[-args.tail:]])


def cmd_operator(ctx: Ctx, args: argparse.Namespace) -> None:
    if args.cmd == "pause":
        t = pause(ctx.store, args.task_id, actor=args.actor, reason=args.reason)
    elif args.cmd == "resume":
        t = resume(ctx.store, args.task_id, actor=args.actor)
    else:
        t = cancel(ctx.store, args.task_id, actor=args.actor, reason=args.reason)
    _out(_task_view(t))


def cmd_approvals(ctx: Ctx, args: argparse.Namespace) -> None:
    _out(ctx.store.approvals(status="PENDING" if args.pending else None))


def cmd_decide(ctx: Ctx, args: argparse.Namespace) -> None:
    _out(decide(ctx.store, args.approval_id, approve=args.cmd == "approve", actor=args.by, note=args.note))


def cmd_recover(ctx: Ctx, args: argparse.Namespace) -> None:
    """After a restart: verify journal, compare replayed vs durable state, surface in-flight mutations."""
    ok, tip = ctx.store.verify_journal()
    report = {"journal_ok": ok, "journal_tip": tip, "tasks": []}
    for t in ctx.store.list_tasks():
        replayed = ctx.store.replay_state(t["task_id"])
        report["tasks"].append({
            "task_id": t["task_id"], "state": t["state"], "replay_matches": replayed["state"] == t["state"]
            and replayed["version"] == t["version"], "lease_owner": t["lease_owner"],
            "inflight_mutations": [m["idempotency_key"] for m in ctx.store.mutations(t["task_id"])
                                   if m["status"] in ("PENDING", "REQUESTED")]})
    if args.run and ok:
        report["resumed"] = [{"task_id": r.task_id, "state": r.state, "last_action": r.action}
                             for r in ctx.supervisor().run_all()]
    _out(report)
    if not ok or not all(t["replay_matches"] for t in report["tasks"]):
        sys.exit(2)


def cmd_merge_confirm(ctx: Ctx, args: argparse.Namespace) -> None:
    t = ctx.store.get_task(args.task_id)
    pending = [m for m in ctx.store.mutations(args.task_id) if m["kind"] == "merge_request" and m["status"] == "REQUESTED"]
    if not pending:
        raise DevWorkflowError("no outstanding merge request for this task")
    gateway = ManualMergeGateway(ctx.layout.merge_requests)
    _out(gateway.confirm(pending[0]["idempotency_key"], merged_head=args.merged_head,
                         source_head=t["approved_head_sha"], merge_ref=args.merge_ref))


def cmd_research(ctx: Ctx, args: argparse.Namespace) -> None:
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    seq = add_external_research(ctx.store, args.task_id, actor=args.actor, source=args.source, text=text)
    _out({"journal_seq": seq, "authority": "none"})


def cmd_refs(ctx: Ctx, args: argparse.Namespace) -> None:
    if args.refs_cmd == "build":
        cfg = ctx.config()
        index = build_index(cfg["repo_root"], external_refs=cfg.get("external_refs", []),
                            include_legacy=not args.no_legacy, evidence_dir=ctx.layout.evidence)
        save_index(index, ctx.layout.references)
        _out({"path": str(ctx.layout.references), "entry_count": index["entry_count"], "repo_head": index["repo_head"],
              "design_references": [e for e in index["entries"] if e["kind"] == "design_reference"]})
    else:
        _out(query(load_index(ctx.layout.references), " ".join(args.text), include_legacy=args.include_legacy,
                   limit=args.limit))


def cmd_replay(ctx: Ctx, args: argparse.Namespace) -> None:
    t = ctx.store.get_task(args.task_id)
    replayed = ctx.store.replay_state(args.task_id)
    match = replayed["state"] == t["state"] and replayed["version"] == t["version"]
    _out({"durable": {"state": t["state"], "version": t["version"]}, "replayed": replayed, "match": match})
    if not match:
        sys.exit(2)


SCENARIOS = {
    "happy": simulation.Script(),
    "test-failure": simulation.Script(qa_fail_times=1),
    "review-reject": simulation.Script(review_reject_times=1),
    "fix-exhaustion": simulation.Script(qa_fail_times=99),
}


def cmd_simulate(ctx: Ctx, args: argparse.Namespace) -> None:
    """Dry run with synthetic agents in a throwaway repo and state dir. No model calls, no network."""
    with tempfile.TemporaryDirectory(prefix="devwf-sim-") as tmp:
        repo, base = simulation.make_repo(tmp)
        store = Store(Path(tmp) / "state.sqlite3")
        try:
            sup = Supervisor(store, simulation.fake_bindings(SCENARIOS[args.scenario]),
                             workspace=WorktreeManager(repo, Path(tmp) / "worktrees"), merge_gateway=FakeMergeGateway())
            sup.intake(simulation.contract("sim-task", base))
            sup.run("sim-task")
            path = [f"{e['from_state']}->{e['to_state']}" for e in store.journal_entries("sim-task")
                    if e["event_type"] == "transition"]
            t = store.get_task("sim-task")
            _out({"scenario": args.scenario, "final_state": t["state"], "block_code": t["block_code"],
                  "fix_cycles": t["fix_cycles"], "transitions": path, "journal_ok": store.verify_journal()[0],
                  "projection": projections.build_projection(store, "sim-task", policy=OwnerDevelopmentPolicy())})
        finally:
            store.close()


def cmd_monitor(ctx: Ctx, args: argparse.Namespace) -> None:
    """Owner-policy monitoring projection(s): what the Personal Command Center may display (read-only)."""
    owner_policy = ctx.owner_policy()
    ids = [args.task_id] if args.task_id else [t["task_id"] for t in ctx.store.list_tasks()]
    _out([projections.build_projection(ctx.store, tid, policy=owner_policy) for tid in ids])


def cmd_events(ctx: Ctx, args: argparse.Namespace) -> None:
    """Idempotent DevelopmentEvent export; the journal remains the source of truth."""
    out = Path(args.out) if args.out else ctx.layout.exports / "events.jsonl"
    events = projections.export_events(ctx.store, args.task_id)
    _out({"path": str(out), "exported": len(events), "appended": append_jsonl(out, events)})


def cmd_control(ctx: Ctx, args: argparse.Namespace) -> None:
    """Apply one abstract control request file under Atlas's own authority table."""
    request = json.loads(Path(args.file).read_text(encoding="utf-8"))
    _out(apply_control(ctx.store, request, authority=ctx.config()["control_authority"]))


def cmd_checkpoint(ctx: Ctx, args: argparse.Namespace) -> None:
    """Record a checkpoint before a context switch, handoff or stop (written only if state changed)."""
    written, checkpoint = projections.record_checkpoint(ctx.store, args.task_id, args.trigger, actor=args.actor)
    _out({"written": written, "checkpoint": checkpoint})


def cmd_glossary(ctx: Ctx, args: argparse.Namespace) -> None:
    if args.term:
        definition = lookup(project.GLOSSARY, " ".join(args.term))
        if definition is None:
            raise DevWorkflowError(f"unknown term {' '.join(args.term)!r}")
        _out({"term": " ".join(args.term), "definition": definition})
    else:
        _out({term: {"definition": d, "aliases": list(a)} for term, (d, a) in sorted(project.GLOSSARY.items())})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atlas-dev-workflow", description=__doc__)
    p.add_argument("--state-dir", help="state directory (default: $ATLAS_DEV_WORKFLOW_HOME or <repo>/.atlas-dev-workflow)")
    p.add_argument("--repo", help="repository root (default: git toplevel of cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create state dir, DB and default config; discover agent CLIs")
    s.add_argument("--probe-versions", action="store_true", help="run `<cli> --version` locally")
    s.set_defaults(fn=cmd_init)
    sub.add_parser("status", help="runtime/schema/journal status").set_defaults(fn=cmd_status)
    s = sub.add_parser("discover", help="list locally installed agent CLIs (never installs)")
    s.add_argument("--probe-versions", action="store_true")
    s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("validate", help="validate executor bindings and optionally a contract file")
    s.add_argument("--contract")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("task", help="task intake/list/show")
    tsub = s.add_subparsers(dest="task_cmd", required=True)
    c = tsub.add_parser("create")
    c.add_argument("file")
    c.add_argument("--actor", default="operator")
    tsub.add_parser("list")
    c = tsub.add_parser("show")
    c.add_argument("task_id")
    s.set_defaults(fn=cmd_task)

    s = sub.add_parser("run", help="advance one task (or all runnable tasks) until it waits or stops")
    s.add_argument("task_id", nargs="?")
    s.add_argument("--max-steps", type=int, default=100)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("journal", help="show or verify the evidence journal")
    s.add_argument("task_id", nargs="?")
    s.add_argument("--tail", type=int, default=200)
    s.add_argument("--verify", action="store_true")
    s.set_defaults(fn=cmd_journal)

    for name in ("pause", "resume", "cancel"):
        s = sub.add_parser(name, help=f"{name} a task")
        s.add_argument("task_id")
        s.add_argument("--actor", default="operator")
        s.add_argument("--reason", default=f"operator {name}")
        s.set_defaults(fn=cmd_operator)

    s = sub.add_parser("approvals", help="list approval requests")
    s.add_argument("--pending", action="store_true")
    s.set_defaults(fn=cmd_approvals)
    for name in ("approve", "reject"):
        s = sub.add_parser(name, help=f"owner {name}s an approval request (never activation)")
        s.add_argument("approval_id")
        s.add_argument("--by", required=True)
        s.add_argument("--note", default="")
        s.set_defaults(fn=cmd_decide)

    s = sub.add_parser("recover", help="post-restart integrity/replay check; --run resumes runnable tasks")
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_recover)
    s = sub.add_parser("replay", help="re-derive a task's state from the journal and compare")
    s.add_argument("task_id")
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("merge-confirm", help="record that the operator merged the requested PR")
    s.add_argument("task_id")
    s.add_argument("--merged-head", required=True)
    s.add_argument("--merge-ref", required=True)
    s.set_defaults(fn=cmd_merge_confirm)

    s = sub.add_parser("research", help="attach external research as planner evidence (no authority)")
    s.add_argument("task_id")
    s.add_argument("--file", required=True)
    s.add_argument("--source", required=True)
    s.add_argument("--actor", default="operator")
    s.set_defaults(fn=cmd_research)

    s = sub.add_parser("refs", help="project reference registry")
    rsub = s.add_subparsers(dest="refs_cmd", required=True)
    b = rsub.add_parser("build")
    b.add_argument("--no-legacy", action="store_true")
    q = rsub.add_parser("query")
    q.add_argument("text", nargs="+")
    q.add_argument("--include-legacy", action="store_true")
    q.add_argument("--limit", type=int, default=8)
    s.set_defaults(fn=cmd_refs)

    s = sub.add_parser("simulate", help="dry-run a synthetic scenario in a throwaway repo")
    s.add_argument("--scenario", choices=sorted(SCENARIOS), default="happy")
    s.set_defaults(fn=cmd_simulate)

    s = sub.add_parser("monitor", help="owner-policy monitoring projection (read-only; for the Command Center)")
    s.add_argument("task_id", nargs="?")
    s.set_defaults(fn=cmd_monitor)
    s = sub.add_parser("events", help="export DevelopmentEvents to JSONL (idempotent)")
    s.add_argument("task_id", nargs="?")
    s.add_argument("--out", help="default: <state-dir>/exports/events.jsonl")
    s.set_defaults(fn=cmd_events)
    s = sub.add_parser("control", help="apply an abstract control-request JSON file (Atlas-enforced)")
    s.add_argument("file")
    s.set_defaults(fn=cmd_control)
    s = sub.add_parser("checkpoint", help="record a durable checkpoint before a context switch/handoff/stop")
    s.add_argument("task_id")
    s.add_argument("--trigger", choices=("context_switch", "handoff", "stop", "risky_command"), default="handoff")
    s.add_argument("--actor", default="operator")
    s.set_defaults(fn=cmd_checkpoint)
    s = sub.add_parser("glossary", help="owner + Atlas vocabulary")
    s.add_argument("term", nargs="*")
    s.set_defaults(fn=cmd_glossary)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = None
    try:
        ctx = Ctx(args) if args.cmd not in ("simulate", "glossary") else None
        args.fn(ctx, args)
    except (OwnerPolicyError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 1
    finally:
        if ctx is not None:
            ctx.close()
    return 0
