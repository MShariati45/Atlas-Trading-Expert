"""Verified private backup/restore with recovery and external-checkpoint evidence."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import time

from atlas2.core.canonical import canonical_json_text
from atlas2.model.data import _digest, _text
from .audit import (
    GENESIS_HASH,
    append_audit_current_transaction,
    append_external_checkpoint,
    audit_head,
    current_recovery_epoch,
    checkpoint_record_digest,
    external_checkpoint_record,
    read_external_checkpoints,
    read_latest_external_checkpoint,
    verify_audit_chain,
)
from .blobs import BlobStore, fsync_directory
from .db import connect
from .migrate import verify_schema
from .repository import Store, child_digest


class StorageFullError(RuntimeError):
    pass


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA trusted_schema=OFF")
    return conn


def _audit_hash_at(conn: sqlite3.Connection, seq: int) -> str | None:
    if type(seq) is not int or seq < 0:
        raise ValueError("audit seq must be nonnegative")
    if seq == 0:
        return GENESIS_HASH
    row = conn.execute(
        "SELECT record_hash FROM sys_audit WHERE seq=?", (seq,)
    ).fetchone()
    return None if row is None else row[0]


def _read_blob(root: Path, digest: str) -> bytes:
    _digest(digest)
    path = root / "raw" / digest
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"raw blob hash mismatch: {digest}")
    return data


def verify(root: str | Path) -> None:
    """Read-only evidence verification; it never creates the raw directory."""
    root = Path(root)
    db_path = root / "atlas.sqlite3"
    if not db_path.is_file():
        raise ValueError("missing database")
    conn = _readonly_connection(db_path)
    try:
        if conn.execute("PRAGMA application_id").fetchone()[0] != 0x41543250:
            raise ValueError("Atlas application_id mismatch")
        if [r[0] for r in conn.execute("PRAGMA integrity_check")] != ["ok"]:
            raise ValueError("SQLite integrity check failed")
        if list(conn.execute("PRAGMA foreign_key_check")):
            raise ValueError("foreign key check failed")
        verify_schema(conn)
        raw_root = root / "raw"
        raw_rows = list(conn.execute("SELECT * FROM raw_blobs ORDER BY blob_sha256"))
        if raw_rows and not raw_root.is_dir():
            raise ValueError("missing raw blob directory")
        for row in raw_rows:
            if len(_read_blob(root, row["blob_sha256"])) != row["byte_size"]:
                raise ValueError("blob size mismatch")
        for row in conn.execute("SELECT * FROM sys_seals"):
            if (
                child_digest(conn, row["aggregate_kind"], row["aggregate_id"])
                != row["child_set_digest"]
            ):
                raise ValueError("seal digest mismatch")
        verify_audit_chain(conn)
    finally:
        conn.close()


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _logical_name(value: str) -> str:
    if type(value) is not str or not value or value in {".", ".."}:
        raise ValueError("backup logical file name required")
    if "/" in value or "\\" in value:
        raise ValueError("backup logical file name must be a basename")
    return value


def _copy_declared_file(source: Path, target: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, target)
    _fsync_file(target)
    fsync_directory(target.parent)
    return _file_hash(target)


def _manifest_bytes(manifest: dict) -> bytes:
    return canonical_json_text(manifest).encode("utf-8")


def _raise_if_disk_full(exc: BaseException, operation: str) -> None:
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        raise StorageFullError(f"disk full during {operation}") from exc


def backup(
    store: Store,
    destination: str | Path,
    *,
    config_policy_files: dict[str, str | Path] | None = None,
    code_ref: dict | None = None,
    lockfile: str | Path | None = None,
    tzdata_version: str = "UNKNOWN",
    external_checkpoint_path: str | Path | None = None,
) -> Path:
    destination = Path(destination)
    if destination.resolve().is_relative_to(store.root.resolve()):
        raise ValueError("backup must be outside the source store")
    if destination.exists():
        raise FileExistsError(destination)
    _text(tzdata_version)
    config_policy_files = {} if config_policy_files is None else dict(config_policy_files)
    code_ref = {} if code_ref is None else code_ref
    canonical_json_text(code_ref)

    work = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )
    created = False
    published = False
    checkpoint_published = False
    try:
        work.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
        db = work / "atlas.sqlite3"
        target = sqlite3.connect(db)
        target.row_factory = sqlite3.Row
        try:
            store.conn.backup(target)
            digests = [
                r[0]
                for r in target.execute(
                    "SELECT blob_sha256 FROM raw_blobs ORDER BY blob_sha256"
                )
            ]
            head_seq, head_hash = audit_head(target)
            recovery_epoch = current_recovery_epoch(target)
        finally:
            target.close()

        blobs = BlobStore(work / "raw")
        for digest in digests:
            blobs.put(store.blobs.read(digest))

        backed_config: dict[str, str] = {}
        for logical_name, source in sorted(config_policy_files.items()):
            name = _logical_name(logical_name)
            rel = f"config/{name}"
            backed_config[rel] = _copy_declared_file(Path(source), work / rel)

        lockfile_rel = None
        if lockfile is not None:
            source = Path(lockfile)
            name = _logical_name(source.name)
            lockfile_rel = f"lockfile/{name}"
            lock_hash = _copy_declared_file(source, work / lockfile_rel)
        else:
            lock_hash = None

        verify(work)
        conn = connect(db)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        files = {"atlas.sqlite3": _file_hash(db)}
        files.update({f"raw/{digest}": digest for digest in digests})
        files.update(backed_config)
        if lockfile_rel is not None:
            files[lockfile_rel] = lock_hash

        manifest = {
            "format": 2,
            "files": files,
            "audit_head": {"seq": head_seq, "hash": head_hash},
            "recovery_epoch": recovery_epoch,
            "config_policy_files": sorted(backed_config),
            "code_ref": code_ref,
            "lockfile": lockfile_rel,
            "tzdata_version": tzdata_version,
        }
        manifest_path = work / "manifest.json"
        manifest_path.write_bytes(_manifest_bytes(manifest))
        _fsync_file(db)
        _fsync_file(manifest_path)
        for child in ("raw", "config", "lockfile"):
            path = work / child
            if path.is_dir():
                fsync_directory(path)
        fsync_directory(work)
        fsync_directory(work.parent)

        # The backup directory becomes visible only after the package is complete.
        os.replace(work, destination)
        published = True
        fsync_directory(destination.parent)

        if external_checkpoint_path is not None:
            previous_checkpoint = read_latest_external_checkpoint(
                external_checkpoint_path
            )
            if previous_checkpoint is not None:
                snapshot = _readonly_connection(destination / "atlas.sqlite3")
                try:
                    ancestor_hash = _audit_hash_at(
                        snapshot, previous_checkpoint["audit_seq"]
                    )
                finally:
                    snapshot.close()
                if ancestor_hash != previous_checkpoint["audit_hash"]:
                    raise ValueError("external checkpoint lineage mismatch")
            manifest_digest = _file_hash(destination / "manifest.json")
            append_external_checkpoint(
                external_checkpoint_path,
                external_checkpoint_record(
                    manifest_digest=manifest_digest,
                    audit_seq=head_seq,
                    audit_hash=head_hash,
                    backup_name=destination.name,
                    previous_checkpoint=previous_checkpoint,
                ),
            )
            checkpoint_published = True

        return destination
    except BaseException as exc:
        if created and work.exists():
            shutil.rmtree(work)
        # Once the verified package has been atomically published, keep it even
        # if the external checkpoint append fails. The caller still receives an
        # explicit error and can retry checkpoint publication; deleting the
        # package here could leave a durable checkpoint line pointing at a
        # backup we just removed.
        _raise_if_disk_full(exc, "backup")
        raise


def _safe_manifest_file(name: str, digest: str, manifest: dict) -> PurePosixPath:
    _digest(digest)
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("invalid backup path")
    if name == "atlas.sqlite3":
        return path
    if len(path.parts) == 2 and path.parts[0] == "raw" and path.parts[1] == digest:
        return path
    if manifest.get("format") == 2:
        allowed = set(manifest.get("config_policy_files", []))
        if manifest.get("lockfile") is not None:
            allowed.add(manifest["lockfile"])
        if name in allowed and path.parts[0] in {"config", "lockfile"}:
            return path
    raise ValueError("invalid backup path")


def _load_manifest(source: Path) -> tuple[dict, bytes]:
    raw = (source / "manifest.json").read_bytes()
    try:
        text = raw.decode("utf-8")
        manifest = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid backup manifest") from exc
    if manifest.get("format") not in {1, 2} or not isinstance(manifest.get("files"), dict):
        raise ValueError("invalid backup manifest")
    if "atlas.sqlite3" not in manifest["files"]:
        raise ValueError("missing backup database")
    if manifest["format"] == 2:
        expected_keys = {
            "format",
            "files",
            "audit_head",
            "recovery_epoch",
            "config_policy_files",
            "code_ref",
            "lockfile",
            "tzdata_version",
        }
        if set(manifest) != expected_keys:
            raise ValueError("invalid backup manifest fields")
        head = manifest["audit_head"]
        if (
            type(head) is not dict
            or set(head) != {"seq", "hash"}
            or type(head["seq"]) is not int
            or head["seq"] < 0
        ):
            raise ValueError("invalid backup audit head")
        _digest(head["hash"])
        if type(manifest["recovery_epoch"]) is not int or manifest["recovery_epoch"] < 1:
            raise ValueError("invalid backup recovery epoch")
        if (
            type(manifest["config_policy_files"]) is not list
            or manifest["config_policy_files"] != sorted(set(manifest["config_policy_files"]))
        ):
            raise ValueError("invalid backup config file list")
        canonical_json_text(manifest["code_ref"])
        if manifest["lockfile"] is not None:
            _text(manifest["lockfile"])
        _text(manifest["tzdata_version"])
    return manifest, raw


def _checkpoint_chain_extends(
    checkpoints: list[dict], base_index: int
) -> bool:
    if not 0 <= base_index < len(checkpoints):
        return False
    previous = checkpoints[base_index]
    for current in checkpoints[base_index + 1:]:
        if current["previous_checkpoint_digest"] != checkpoint_record_digest(previous):
            return False
        if (
            current["parent_audit_seq"] != previous["audit_seq"]
            or current["parent_audit_hash"] != previous["audit_hash"]
        ):
            return False
        if current["audit_seq"] < previous["audit_seq"]:
            return False
        previous = current
    return True


def _missing_tail_status(
    backup_seq: int,
    backup_hash: str,
    checkpoints: list[dict],
    *,
    base_index: int | None,
) -> tuple[str, str | None]:
    if not checkpoints:
        return "UNKNOWN", None
    latest = checkpoints[-1]
    latest_hash = latest["audit_hash"]
    if latest["audit_seq"] == backup_seq and latest_hash == backup_hash:
        return "NONE", latest_hash
    if (
        base_index is not None
        and latest["audit_seq"] > backup_seq
        and _checkpoint_chain_extends(checkpoints, base_index)
    ):
        return "KNOWN_RANGE", latest_hash
    return "UNKNOWN", latest_hash


def restore(
    source: str | Path,
    destination: str | Path,
    *,
    external_checkpoint_path: str | Path | None = None,
) -> Path:
    source, destination = Path(source), Path(destination)
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("restore must be outside the source backup")
    manifest, manifest_raw = _load_manifest(source)
    files = manifest["files"]

    for name, digest in files.items():
        path = _safe_manifest_file(name, digest, manifest)
        source_file = source.joinpath(*path.parts)
        if _file_hash(source_file) != digest:
            raise ValueError("backup hash mismatch")

    created = False
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = True
        for name, digest in files.items():
            path = _safe_manifest_file(name, digest, manifest)
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source.joinpath(*path.parts), target)
            if _file_hash(target) != digest:
                raise ValueError("restored file hash mismatch")

        verify(destination)
        conn = _readonly_connection(destination / "atlas.sqlite3")
        try:
            required_raw = {
                f"raw/{r[0]}" for r in conn.execute("SELECT blob_sha256 FROM raw_blobs")
            }
            manifest_raw_files = {name for name in files if name.startswith("raw/")}
            if manifest_raw_files != required_raw:
                raise ValueError("backup blob inventory mismatch")
            restored_head_seq, restored_head_hash = audit_head(conn)
            if manifest["format"] == 2:
                if (
                    restored_head_seq != manifest["audit_head"]["seq"]
                    or restored_head_hash != manifest["audit_head"]["hash"]
                ):
                    raise ValueError("backup audit head mismatch")
                if current_recovery_epoch(conn) != manifest["recovery_epoch"]:
                    raise ValueError("backup recovery epoch mismatch")
        finally:
            conn.close()

        manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
        checkpoints = (
            read_external_checkpoints(external_checkpoint_path)
            if external_checkpoint_path is not None
            else []
        )
        checkpoint = checkpoints[-1] if checkpoints else None
        matching_indexes = [
            index
            for index, item in enumerate(checkpoints)
            if item["manifest_digest"] == manifest_digest
        ]
        base_index = matching_indexes[-1] if matching_indexes else None
        if base_index is not None:
            match = checkpoints[base_index]
            if (
                match["audit_seq"] != restored_head_seq
                or match["audit_hash"] != restored_head_hash
            ):
                raise ValueError("external checkpoint head mismatch")
        elif checkpoint is not None and checkpoint["audit_seq"] <= restored_head_seq:
            chain = _readonly_connection(destination / "atlas.sqlite3")
            try:
                ancestor_hash = _audit_hash_at(chain, checkpoint["audit_seq"])
            finally:
                chain.close()
            if ancestor_hash != checkpoint["audit_hash"]:
                raise ValueError("external checkpoint manifest mismatch")
        missing_tail, external_hash = _missing_tail_status(
            restored_head_seq,
            restored_head_hash,
            checkpoints,
            base_index=base_index,
        )
        conn = connect(destination / "atlas.sqlite3")
        try:
            conn.execute("BEGIN IMMEDIATE")
            new_epoch = current_recovery_epoch(conn) + 1
            conn.execute(
                "INSERT INTO sys_recovery_epochs VALUES (?,?,?,?,?,?)",
                (
                    new_epoch,
                    manifest_digest,
                    restored_head_seq,
                    restored_head_hash,
                    external_hash,
                    missing_tail,
                ),
            )
            append_audit_current_transaction(
                conn,
                event_type="RESTORE",
                actor_kind="SYSTEM",
                actor_id="atlas2",
                occurred_at_us=time.time_ns() // 1_000,
                subject_table="sys_recovery_epochs",
                subject_id=str(new_epoch),
                payload={
                    "manifest_digest": manifest_digest,
                    "restored_head_seq": restored_head_seq,
                    "restored_head_hash": restored_head_hash,
                    "missing_tail": missing_tail,
                },
                recovery_epoch=new_epoch,
            )
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

        verify(destination)

        for name in files:
            target = destination.joinpath(*PurePosixPath(name).parts)
            _fsync_file(target)
        for child in ("raw", "config", "lockfile"):
            path = destination / child
            if path.is_dir():
                fsync_directory(path)
        fsync_directory(destination)
        fsync_directory(destination.parent)
        return destination
    except BaseException as exc:
        if created and destination.exists():
            shutil.rmtree(destination)
        _raise_if_disk_full(exc, "restore")
        raise
