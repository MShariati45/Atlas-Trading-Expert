"""Durable SQLite state for the development workflow (separate from any Atlas product/research DB).

- tasks: one row per task, optimistic `version` + lease fencing `lease_token` on every write
- journal: append-only, hash-chained evidence journal (UPDATE/DELETE blocked by triggers)
- agent_runs: recorded agent outputs keyed by deterministic step_key (replay without re-invocation)
- approvals: owner approval requests; activation_allowed is constrained to 0
- external_mutations: idempotency ledger for Git/PR/merge side effects
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .contracts import canonical_json
from .errors import StaleLease, StateStoreError
from .states import State, validate_transition

SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64

_SCHEMA_V1 = """
CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE tasks(
  task_id TEXT PRIMARY KEY,
  contract_json TEXT NOT NULL,
  contract_digest TEXT NOT NULL,
  task_class TEXT NOT NULL CHECK(task_class IN ('A','B','C')),
  classification_json TEXT NOT NULL,
  state TEXT NOT NULL,
  origin_state TEXT,
  block_code TEXT,
  block_reason TEXT,
  fix_cycles INTEGER NOT NULL DEFAULT 0,
  max_fix_cycles INTEGER NOT NULL CHECK(max_fix_cycles BETWEEN 1 AND 5),
  version INTEGER NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_token INTEGER NOT NULL DEFAULT 0,
  lease_expires_us INTEGER,
  branch TEXT NOT NULL UNIQUE,
  worktree_path TEXT UNIQUE,
  base_sha TEXT NOT NULL,
  head_sha TEXT,
  approved_head_sha TEXT,
  created_us INTEGER NOT NULL,
  updated_us INTEGER NOT NULL
);
CREATE TABLE journal(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  actor TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  entry_hash TEXT NOT NULL UNIQUE,
  created_us INTEGER NOT NULL
);
CREATE TRIGGER journal_no_update BEFORE UPDATE ON journal BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER journal_no_delete BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TABLE agent_runs(
  step_key TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  role TEXT NOT NULL,
  executor_id TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OK','INVALID_OUTPUT','PROVIDER_ERROR')),
  packet_json TEXT,
  output_digest TEXT,
  output_excerpt TEXT,
  created_us INTEGER NOT NULL
);
CREATE TABLE approvals(
  approval_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  head_sha TEXT NOT NULL,
  categories_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
  activation_allowed INTEGER NOT NULL DEFAULT 0 CHECK(activation_allowed = 0),
  decided_by TEXT,
  decision_note TEXT,
  created_us INTEGER NOT NULL,
  decided_us INTEGER
);
CREATE TABLE external_mutations(
  idempotency_key TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id),
  kind TEXT NOT NULL,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING','REQUESTED','DONE','FAILED')),
  result_json TEXT,
  created_us INTEGER NOT NULL,
  updated_us INTEGER NOT NULL
);
CREATE INDEX journal_task ON journal(task_id, seq);
"""

_MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1}


def system_clock_us() -> int:
    return time.time_ns() // 1000


def _entry_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + "\x00" + canonical_json(fields)).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: str | Path, *, clock: Callable[[], int] = system_clock_us):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._migrate()
        except BaseException:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    # -- schema -----------------------------------------------------------------------------------

    def schema_version(self) -> int:
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
        if not exists:
            return 0
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0

    def _migrate(self) -> None:
        current = self.schema_version()
        if current > SCHEMA_VERSION:
            raise StateStoreError(f"state DB schema {current} is newer than runtime {SCHEMA_VERSION}")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            # executescript runs the whole forward-only migration and version bump as one transaction.
            self.conn.executescript(
                "BEGIN IMMEDIATE;" + _MIGRATIONS[version]
                + f"INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','{version}');COMMIT;")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # -- journal ----------------------------------------------------------------------------------

    def _append(self, task_id: str, event_type: str, actor: str, payload: dict[str, Any],
                from_state: str | None = None, to_state: str | None = None) -> int:
        row = self.conn.execute("SELECT entry_hash FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row["entry_hash"] if row else GENESIS_HASH
        now = self.clock()
        payload_json = canonical_json(payload)
        fields = {"task_id": task_id, "event_type": event_type, "from_state": from_state, "to_state": to_state,
                  "actor": actor, "payload_json": payload_json, "created_us": now}
        entry = _entry_hash(prev, fields)
        cur = self.conn.execute(
            "INSERT INTO journal(task_id,event_type,from_state,to_state,actor,payload_json,prev_hash,entry_hash,created_us)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (task_id, event_type, from_state, to_state, actor, payload_json, prev, entry, now))
        return int(cur.lastrowid)

    def journal(self, task_id: str, event_type: str, actor: str, payload: dict[str, Any]) -> int:
        with self.tx():
            return self._append(task_id, event_type, actor, payload)

    def journal_entries(self, task_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM journal" + (" WHERE task_id=?" if task_id else "") + " ORDER BY seq"
        rows = self.conn.execute(sql, (task_id,) if task_id else ())
        return [dict(r) | {"payload": json.loads(r["payload_json"])} for r in rows]

    def verify_journal(self) -> tuple[bool, str]:
        prev = GENESIS_HASH
        for r in self.conn.execute("SELECT * FROM journal ORDER BY seq"):
            fields = {k: r[k] for k in ("task_id", "event_type", "from_state", "to_state", "actor",
                                        "payload_json", "created_us")}
            if r["prev_hash"] != prev or _entry_hash(prev, fields) != r["entry_hash"]:
                return False, f"hash chain broken at seq {r['seq']}"
            prev = r["entry_hash"]
        return True, prev

    # -- tasks ------------------------------------------------------------------------------------

    def create_task(self, *, task_id: str, contract: dict[str, Any], contract_digest: str,
                    classification: dict[str, Any], branch: str, base_sha: str, max_fix_cycles: int,
                    actor: str) -> dict[str, Any]:
        now = self.clock()
        with self.tx():
            existing = self.conn.execute("SELECT contract_digest FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if existing:
                if existing["contract_digest"] == contract_digest:
                    return self.get_task(task_id)  # idempotent re-intake of the identical contract
                raise StateStoreError(f"task {task_id} already exists with a different contract")
            clash = self.conn.execute("SELECT task_id FROM tasks WHERE branch=?", (branch,)).fetchone()
            if clash:
                raise StateStoreError(f"branch {branch} already bound to task {clash['task_id']}")
            self.conn.execute(
                "INSERT INTO tasks(task_id,contract_json,contract_digest,task_class,classification_json,state,"
                "max_fix_cycles,branch,base_sha,created_us,updated_us) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, canonical_json(contract), contract_digest, classification["task_class"],
                 canonical_json(classification), State.NEW_TASK.value, max_fix_cycles, branch, base_sha, now, now))
            self._append(task_id, "task_created", actor,
                         {"contract_digest": contract_digest, "classification": classification,
                          "branch": branch, "base_sha": base_sha}, None, State.NEW_TASK.value)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise StateStoreError(f"unknown task {task_id}")
        return dict(row)

    def list_tasks(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM tasks ORDER BY created_us, task_id")]

    # -- leases (fencing) -------------------------------------------------------------------------

    def acquire_lease(self, task_id: str, worker_id: str, ttl_us: int) -> int:
        now = self.clock()
        with self.tx():
            t = self.get_task(task_id)
            held = t["lease_owner"] and t["lease_owner"] != worker_id and (t["lease_expires_us"] or 0) > now
            if held:
                raise StaleLease(f"task {task_id} is leased by {t['lease_owner']}")
            token = t["lease_token"] + 1
            self.conn.execute("UPDATE tasks SET lease_owner=?, lease_token=?, lease_expires_us=? WHERE task_id=?",
                              (worker_id, token, now + ttl_us, task_id))
            self._append(task_id, "lease_acquired", worker_id, {"token": token, "expires_us": now + ttl_us})
        return token

    def release_lease(self, task_id: str, worker_id: str, token: int) -> None:
        with self.tx():
            self.conn.execute("UPDATE tasks SET lease_owner=NULL, lease_expires_us=NULL "
                              "WHERE task_id=? AND lease_owner=? AND lease_token=?", (task_id, worker_id, token))

    def check_lease(self, task_id: str, worker_id: str, token: int) -> None:
        t = self.get_task(task_id)
        if t["lease_owner"] != worker_id or t["lease_token"] != token or (t["lease_expires_us"] or 0) <= self.clock():
            raise StaleLease(f"stale lease for {task_id}: worker={worker_id} token={token} "
                             f"(current owner={t['lease_owner']} token={t['lease_token']})")

    # -- transitions ------------------------------------------------------------------------------

    def transition(self, task_id: str, to_state: State, *, actor: str, reason: str,
                   expected_version: int, lease: tuple[str, int] | None = None,
                   updates: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        """Atomically validate and apply one state transition plus its journal entry.

        Workers must pass their lease (worker_id, token); operator commands pass lease=None and
        revoke any outstanding lease by bumping the fencing token.
        """
        updates = dict(updates or {})
        with self.tx():
            t = self.get_task(task_id)
            if t["version"] != expected_version:
                raise StaleLease(f"task {task_id} version {t['version']} != expected {expected_version}")
            if lease is not None:
                worker, token = lease
                if t["lease_owner"] != worker or t["lease_token"] != token or (t["lease_expires_us"] or 0) <= self.clock():
                    raise StaleLease(f"stale lease for {task_id}: worker={worker} token={token}")
            src = State(t["state"])
            validate_transition(src, to_state, origin=t["origin_state"])
            if to_state in (State.PAUSED, State.BLOCKED):
                updates.setdefault("origin_state", src.value if src not in (State.PAUSED, State.BLOCKED) else t["origin_state"])
            elif src in (State.PAUSED, State.BLOCKED):
                updates.setdefault("origin_state", None)
            if to_state is not State.BLOCKED:
                updates.setdefault("block_code", None)
                updates.setdefault("block_reason", None)
            sets = {**updates, "state": to_state.value, "version": t["version"] + 1, "updated_us": self.clock()}
            if lease is None:
                sets.update({"lease_owner": None, "lease_expires_us": None, "lease_token": t["lease_token"] + 1})
            cols = ", ".join(f"{k}=?" for k in sets)
            self.conn.execute(f"UPDATE tasks SET {cols} WHERE task_id=? AND version=?",
                              (*sets.values(), task_id, expected_version))
            snapshot = {k: sets.get(k, t[k]) for k in ("fix_cycles", "head_sha", "origin_state", "block_code",
                                                       "worktree_path", "approved_head_sha")}
            self._append(task_id, "transition", actor,
                         {"reason": reason, "version": t["version"] + 1, "state_after": snapshot,
                          "evidence": evidence or {}}, src.value, to_state.value)
        return self.get_task(task_id)

    def replay_state(self, task_id: str) -> dict[str, Any]:
        """Re-derive durable task state purely from the journal (deterministic replay check)."""
        state, version, snapshot = None, 0, {}
        for entry in self.journal_entries(task_id):
            if entry["event_type"] == "task_created":
                state = entry["to_state"]
            elif entry["event_type"] == "transition":
                if entry["from_state"] != state:
                    raise StateStoreError(f"journal discontinuity at seq {entry['seq']}")
                validate_transition(entry["from_state"], entry["to_state"], origin=snapshot.get("origin_state"))
                state = entry["to_state"]
                version = entry["payload"]["version"]
                snapshot = dict(entry["payload"]["state_after"])
        return {"state": state, "version": version, **snapshot}

    # -- agent runs -------------------------------------------------------------------------------

    def get_agent_run(self, step_key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM agent_runs WHERE step_key=?", (step_key,)).fetchone()
        return dict(row) if row else None

    def record_agent_run(self, *, step_key: str, task_id: str, role: str, executor_id: str, attempts: int,
                         status: str, packet: dict[str, Any] | None, output_digest: str | None,
                         output_excerpt: str, lease: tuple[str, int],
                         telemetry: dict[str, Any] | None = None) -> None:
        """Record the step outcome; `telemetry` (usage, context/output truncation, effort) goes to the journal."""
        with self.tx():
            self.check_lease(task_id, *lease)
            self.conn.execute(
                "INSERT INTO agent_runs(step_key,task_id,role,executor_id,attempts,status,packet_json,output_digest,"
                "output_excerpt,created_us) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (step_key, task_id, role, executor_id, attempts, status,
                 None if packet is None else canonical_json(packet), output_digest, output_excerpt, self.clock()))
            self._append(task_id, "agent_packet", lease[0],
                         {"step_key": step_key, "role": role, "executor_id": executor_id, "attempts": attempts,
                          "status": status, "output_digest": output_digest,
                          "packet_digest": None if packet is None else hashlib.sha256(
                              canonical_json(packet).encode()).hexdigest(),
                          "packet": packet, **(telemetry or {})})

    def agent_runs(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=? ORDER BY rowid", (task_id,))]  # insertion order

    # -- approvals --------------------------------------------------------------------------------

    def open_approval(self, *, approval_id: str, task_id: str, head_sha: str, categories: list[str], actor: str) -> dict[str, Any]:
        with self.tx():
            row = self.conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO approvals(approval_id,task_id,head_sha,categories_json,status,created_us)"
                    " VALUES(?,?,?,?,'PENDING',?)",
                    (approval_id, task_id, head_sha, canonical_json(categories), self.clock()))
                self._append(task_id, "approval_requested", actor,
                             {"approval_id": approval_id, "head_sha": head_sha, "categories": categories,
                              "activation_allowed": False})
        return self.get_approval(approval_id)

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if row is None:
            raise StateStoreError(f"unknown approval {approval_id}")
        return dict(row)

    def approvals(self, task_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM approvals WHERE 1=1", []
        if task_id:
            sql, args = sql + " AND task_id=?", args + [task_id]
        if status:
            sql, args = sql + " AND status=?", args + [status]
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY created_us", args)]

    def decide_approval(self, approval_id: str, *, approve: bool, decided_by: str, note: str) -> dict[str, Any]:
        with self.tx():
            a = self.get_approval(approval_id)
            if a["status"] != "PENDING":
                raise StateStoreError(f"approval {approval_id} already {a['status']}")
            status = "APPROVED" if approve else "REJECTED"
            self.conn.execute("UPDATE approvals SET status=?, decided_by=?, decision_note=?, decided_us=? "
                              "WHERE approval_id=? AND status='PENDING'",
                              (status, decided_by, note, self.clock(), approval_id))
            self._append(a["task_id"], "approval_decided", decided_by,
                         {"approval_id": approval_id, "status": status, "head_sha": a["head_sha"], "note": note,
                          "activation_allowed": False})
        return self.get_approval(approval_id)

    # -- external mutation idempotency ------------------------------------------------------------

    def begin_mutation(self, key: str, *, task_id: str, kind: str, request: dict[str, Any], actor: str) -> dict[str, Any]:
        """Insert a PENDING mutation, or return the existing record without re-executing."""
        with self.tx():
            row = self.conn.execute("SELECT * FROM external_mutations WHERE idempotency_key=?", (key,)).fetchone()
            if row is not None:
                if row["request_json"] != canonical_json(request):  # same key must mean the same request
                    raise StateStoreError(f"idempotency key {key} reused with a different request")
                self._append(task_id, "mutation_deduplicated", actor, {"idempotency_key": key, "status": row["status"]})
                return dict(row) | {"created": False}
            now = self.clock()
            self.conn.execute(
                "INSERT INTO external_mutations(idempotency_key,task_id,kind,request_json,status,created_us,updated_us)"
                " VALUES(?,?,?,?,'PENDING',?,?)", (key, task_id, kind, canonical_json(request), now, now))
            self._append(task_id, "mutation_started", actor, {"idempotency_key": key, "kind": kind, "request": request})
        return dict(self.conn.execute("SELECT * FROM external_mutations WHERE idempotency_key=?", (key,)).fetchone()) | {"created": True}

    def finish_mutation(self, key: str, *, status: str, result: dict[str, Any], actor: str) -> None:
        """PENDING -> REQUESTED (gateway accepted, awaiting completion) -> DONE/FAILED."""
        allowed = {"REQUESTED": ("PENDING",), "DONE": ("PENDING", "REQUESTED"), "FAILED": ("PENDING", "REQUESTED")}
        with self.tx():
            row = self.conn.execute("SELECT * FROM external_mutations WHERE idempotency_key=?", (key,)).fetchone()
            if row is None or row["status"] not in allowed[status]:
                raise StateStoreError(f"mutation {key} cannot move to {status}")
            self.conn.execute("UPDATE external_mutations SET status=?, result_json=?, updated_us=? WHERE idempotency_key=?",
                              (status, canonical_json(result), self.clock(), key))
            self._append(row["task_id"], "mutation_finished", actor,
                         {"idempotency_key": key, "status": status, "result": result})

    def get_mutation(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM external_mutations WHERE idempotency_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def mutations(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM external_mutations WHERE task_id=? ORDER BY created_us, idempotency_key", (task_id,))]
