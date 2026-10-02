"""Hash-chained audit evidence and external checkpoint helpers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from atlas2.core.canonical import canonical_json_text, domain_digest, validate_canonical_json_text
from atlas2.core.time import validate_utc_micros
from atlas2.model.data import _digest, _text
from .blobs import fsync_directory

GENESIS_HASH = "0" * 64


def current_recovery_epoch(conn) -> int:
    row = conn.execute("SELECT max(epoch) FROM sys_recovery_epochs").fetchone()
    if row is None or row[0] is None:
        raise ValueError("missing recovery epoch")
    return int(row[0])


def audit_head(conn) -> tuple[int, str]:
    row = conn.execute(
        "SELECT seq,record_hash FROM sys_audit ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    return (0, GENESIS_HASH) if row is None else (int(row[0]), row[1])


def _event_hash(
    *,
    seq: int,
    recovery_epoch: int,
    event_type: str,
    actor_kind: str,
    actor_id: str,
    occurred_at_us: int,
    subject_table: str | None,
    subject_id: str | None,
    payload_json: str,
    prev_hash: str,
) -> str:
    validate_canonical_json_text(payload_json)
    _digest(prev_hash)
    return domain_digest(
        "audit-event-v1",
        {
            "seq": seq,
            "recovery_epoch": recovery_epoch,
            "event_type": event_type,
            "actor_kind": actor_kind,
            "actor_id": actor_id,
            "occurred_at_us": occurred_at_us,
            "subject_table": subject_table,
            "subject_id": subject_id,
            "payload": json.loads(payload_json),
            "prev_hash": prev_hash,
        },
    )


def append_audit_current_transaction(
    conn,
    *,
    event_type: str,
    actor_kind: str,
    actor_id: str,
    occurred_at_us: int,
    subject_table: str | None = None,
    subject_id: str | None = None,
    payload: object,
    recovery_epoch: int | None = None,
) -> tuple[int, str]:
    if not conn.in_transaction:
        raise RuntimeError("audit append requires an active transaction")
    for value in (event_type, actor_kind, actor_id):
        _text(value)
    if subject_table is not None:
        _text(subject_table)
    if subject_id is not None:
        _text(subject_id)
    validate_utc_micros(occurred_at_us)
    epoch = current_recovery_epoch(conn) if recovery_epoch is None else recovery_epoch
    if not conn.execute(
        "SELECT 1 FROM sys_recovery_epochs WHERE epoch=?", (epoch,)
    ).fetchone():
        raise ValueError("unknown audit recovery epoch")
    head_seq, prev_hash = audit_head(conn)
    seq = head_seq + 1
    payload_json = canonical_json_text(payload)
    record_hash = _event_hash(
        seq=seq,
        recovery_epoch=epoch,
        event_type=event_type,
        actor_kind=actor_kind,
        actor_id=actor_id,
        occurred_at_us=occurred_at_us,
        subject_table=subject_table,
        subject_id=subject_id,
        payload_json=payload_json,
        prev_hash=prev_hash,
    )
    conn.execute(
        "INSERT INTO sys_audit VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            seq,
            epoch,
            event_type,
            actor_kind,
            actor_id,
            occurred_at_us,
            subject_table,
            subject_id,
            payload_json,
            prev_hash,
            record_hash,
        ),
    )
    return seq, record_hash


def verify_audit_chain(conn) -> tuple[int, str]:
    prev_hash = GENESIS_HASH
    expected_seq = 1
    for row in conn.execute("SELECT * FROM sys_audit ORDER BY seq"):
        if row["seq"] != expected_seq:
            raise ValueError("audit sequence gap")
        if row["prev_hash"] != prev_hash:
            raise ValueError("audit previous-hash mismatch")
        if not conn.execute(
            "SELECT 1 FROM sys_recovery_epochs WHERE epoch=?",
            (row["recovery_epoch"],),
        ).fetchone():
            raise ValueError("audit references unknown recovery epoch")
        expected_hash = _event_hash(
            seq=row["seq"],
            recovery_epoch=row["recovery_epoch"],
            event_type=row["event_type"],
            actor_kind=row["actor_kind"],
            actor_id=row["actor_id"],
            occurred_at_us=row["occurred_at_us"],
            subject_table=row["subject_table"],
            subject_id=row["subject_id"],
            payload_json=row["payload"],
            prev_hash=row["prev_hash"],
        )
        if row["record_hash"] != expected_hash:
            raise ValueError("audit record-hash mismatch")
        prev_hash = expected_hash
        expected_seq += 1
    return expected_seq - 1, prev_hash


def _validate_checkpoint_record(record: dict) -> dict:
    expected = {
        "manifest_digest",
        "audit_seq",
        "audit_hash",
        "backup_name",
        "parent_audit_seq",
        "parent_audit_hash",
        "previous_checkpoint_digest",
    }
    if type(record) is not dict or set(record) != expected:
        raise ValueError("invalid external checkpoint record")
    _digest(record["manifest_digest"])
    _digest(record["audit_hash"])
    _text(record["backup_name"])
    if type(record["audit_seq"]) is not int or record["audit_seq"] < 0:
        raise ValueError("invalid external checkpoint seq")
    parent_values = (
        record["parent_audit_seq"],
        record["parent_audit_hash"],
        record["previous_checkpoint_digest"],
    )
    if all(value is None for value in parent_values):
        return record
    if any(value is None for value in parent_values):
        raise ValueError("incomplete external checkpoint lineage")
    if type(record["parent_audit_seq"]) is not int or record["parent_audit_seq"] < 0:
        raise ValueError("invalid checkpoint parent seq")
    _digest(record["parent_audit_hash"])
    _digest(record["previous_checkpoint_digest"])
    if record["audit_seq"] < record["parent_audit_seq"]:
        raise ValueError("checkpoint sequence regressed")
    if (
        record["audit_seq"] == record["parent_audit_seq"]
        and record["audit_hash"] != record["parent_audit_hash"]
    ):
        raise ValueError("checkpoint hash changed without sequence advance")
    return record


def checkpoint_record_digest(record: dict) -> str:
    _validate_checkpoint_record(record)
    return domain_digest("external-checkpoint-record-v2", record)


def external_checkpoint_record(
    *,
    manifest_digest: str,
    audit_seq: int,
    audit_hash: str,
    backup_name: str,
    previous_checkpoint: dict | None = None,
) -> dict:
    _digest(manifest_digest)
    _digest(audit_hash)
    _text(backup_name)
    if type(audit_seq) is not int or audit_seq < 0:
        raise ValueError("audit_seq must be nonnegative")
    if previous_checkpoint is None:
        parent_audit_seq = None
        parent_audit_hash = None
        previous_checkpoint_digest = None
    else:
        _validate_checkpoint_record(previous_checkpoint)
        parent_audit_seq = previous_checkpoint["audit_seq"]
        parent_audit_hash = previous_checkpoint["audit_hash"]
        previous_checkpoint_digest = checkpoint_record_digest(previous_checkpoint)
    record = {
        "manifest_digest": manifest_digest,
        "audit_seq": audit_seq,
        "audit_hash": audit_hash,
        "backup_name": backup_name,
        "parent_audit_seq": parent_audit_seq,
        "parent_audit_hash": parent_audit_hash,
        "previous_checkpoint_digest": previous_checkpoint_digest,
    }
    return _validate_checkpoint_record(record)


def _parse_checkpoint_bytes(raw: bytes) -> list[dict]:
    if raw and not raw.endswith(b"\n"):
        raise ValueError("torn external checkpoint tail")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid external checkpoint encoding") from exc
    records: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        validate_canonical_json_text(line)
        value = _validate_checkpoint_record(json.loads(line))
        if records:
            previous = records[-1]
            if value["previous_checkpoint_digest"] != checkpoint_record_digest(previous):
                raise ValueError("external checkpoint chain digest mismatch")
            if (
                value["parent_audit_seq"] != previous["audit_seq"]
                or value["parent_audit_hash"] != previous["audit_hash"]
            ):
                raise ValueError("external checkpoint audit lineage mismatch")
        elif value["previous_checkpoint_digest"] is not None:
            raise ValueError("external checkpoint chain has no genesis")
        records.append(value)
    return records


def _lock_checkpoint_file(stream) -> None:
    if os.name == "nt":
        import msvcrt
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _unlock_checkpoint_file(stream) -> None:
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def append_external_checkpoint(path: str | Path, record: dict) -> None:
    _validate_checkpoint_record(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    with lock_path.open("a+b") as lock_stream:
        _lock_checkpoint_file(lock_stream)
        try:
            raw = target.read_bytes() if target.exists() else b""
            records = _parse_checkpoint_bytes(raw)
            if records:
                previous = records[-1]
                if (
                    record["previous_checkpoint_digest"]
                    != checkpoint_record_digest(previous)
                    or record["parent_audit_seq"] != previous["audit_seq"]
                    or record["parent_audit_hash"] != previous["audit_hash"]
                ):
                    raise ValueError("external checkpoint append lineage mismatch")
            elif record["previous_checkpoint_digest"] is not None:
                raise ValueError("external checkpoint append missing genesis")

            line = canonical_json_text(record).encode("utf-8") + b"\n"
            with target.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            _unlock_checkpoint_file(lock_stream)
    fsync_directory(target.parent)


def read_external_checkpoints(path: str | Path) -> list[dict]:
    target = Path(path)
    if not target.is_file():
        return []
    return _parse_checkpoint_bytes(target.read_bytes())


def read_latest_external_checkpoint(path: str | Path) -> dict | None:
    records = read_external_checkpoints(path)
    return records[-1] if records else None
