"""Validated append-only repository. SQL identifiers come only from fixed maps."""
from contextlib import contextmanager
from dataclasses import asdict
from enum import Enum
from pathlib import Path
import sqlite3
import time
from typing import Callable

from atlas2.core.canonical import domain_digest
from atlas2.model.data import (
    RawBlob, SourceObservation, BarFact, QuoteFact, CalendarScheduleFact,
    CalendarValueFact, FactLink, DatasetVersion, DatasetMembership,
)
from .blobs import BlobStore
from .db import connect
from .migrate import apply_migrations
from .records import RequestResult, RunManifest, RunAttemptStart, RunAttemptEnd


class ConflictKind(str, Enum):
    IDEMPOTENT_REPEAT = 'IDEMPOTENT_REPEAT'
    IDENTITY_CONFLICT = 'IDENTITY_CONFLICT'
    LOGICAL_KEY_CONFLICT = 'LOGICAL_KEY_CONFLICT'
    SEAL_VIOLATION = 'SEAL_VIOLATION'


class StoreConflict(ValueError):
    def __init__(self, kind: ConflictKind):
        self.kind = kind
        super().__init__(kind.value)


TABLES = {
    RawBlob: ('raw_blobs', ('blob_sha256',)),
    SourceObservation: ('source_observations', ('obs_id',)),
    BarFact: ('data_bar_facts', ('fact_id',)),
    QuoteFact: ('data_quote_facts', ('fact_id',)),
    CalendarScheduleFact: ('data_calendar_schedule_facts', ('fact_id',)),
    CalendarValueFact: ('data_calendar_value_facts', ('fact_id',)),
    FactLink: ('data_fact_links', ('fact_id', 'obs_id', 'locator')),
    DatasetVersion: ('data_datasets', ('dataset_id',)),
    DatasetMembership: ('data_dataset_membership', ('dataset_id', 'fact_kind', 'fact_id', 'obs_id', 'locator')),
    RunManifest: ('run_manifests', ('manifest_id',)),
    RunAttemptStart: ('run_attempt_starts', ('attempt_id',)),
    RunAttemptEnd: ('run_attempt_ends', ('attempt_id',)),
}
# Registered aggregate -> (parent key, child table, child FK, deterministic order).
CHILDREN = {
    'run_manifests': ('manifest_id', 'run_attempt_starts', 'manifest_id', 'attempt_id'),
    'run_attempt_starts': ('attempt_id', 'run_attempt_ends', 'attempt_id', 'attempt_id'),
    'data_datasets': (
        'dataset_id',
        'data_dataset_membership',
        'dataset_id',
        'fact_kind,fact_id,obs_id,locator',
    ),
    'label_groups': (
        'group_id',
        'label_interpretations',
        'group_id',
        'rank,interpretation_id',
    ),
    'capture_units': (
        'capture_unit_id',
        'capture_unit_members',
        'capture_unit_id',
        'member_kind,content_digest',
    ),
    'evaluation_contexts': (
        'ctx_id',
        'evaluation_unit_members',
        'ctx_id',
        'member_kind,content_digest',
    ),
    'outcome_batches': (
        'batch_id',
        'outcome_batch_members',
        'batch_id',
        'content_digest',
    ),
}


def child_digest(conn: sqlite3.Connection, kind: str, aggregate_id: str) -> str:
    _, child, fk, order = CHILDREN[kind]
    import hashlib
    h = hashlib.sha256(b'ATLAS2\x00child-set-v1\x00')
    if kind in {'capture_units', 'evaluation_contexts', 'outcome_batches'}:
        rows = conn.execute(
            f'SELECT * FROM {child} WHERE {fk}=? ORDER BY {order}',
            (aggregate_id,),
        ).fetchall()
        for row in rows:
            semantic = {k: row[k] for k in row.keys() if k in {'member_kind', 'content_digest', 'outcome_id'}}
            if kind == 'outcome_batches':
                semantic = {'content_digest': row['content_digest']}
            h.update(bytes.fromhex(domain_digest('child-row-v1', semantic)))
        return h.hexdigest()
    if kind == 'label_groups':
        rows = conn.execute(
            'SELECT * FROM label_interpretations WHERE group_id=? '
            'ORDER BY rank,interpretation_id',
            (aggregate_id,),
        ).fetchall()
        for row in rows:
            anchors = [
                dict(anchor)
                for anchor in conn.execute(
                    'SELECT * FROM label_anchors WHERE interpretation_id=? '
                    'ORDER BY role,anchor_id',
                    (row['interpretation_id'],),
                )
            ]
            h.update(bytes.fromhex(domain_digest(
                'child-row-v1',
                {'interpretation': dict(row), 'anchors': anchors},
            )))
        return h.hexdigest()
    rows = [
        dict(r)
        for r in conn.execute(
            f'SELECT * FROM {child} WHERE {fk}=? ORDER BY {order}',
            (aggregate_id,),
        )
    ]
    for row in rows:
        h.update(bytes.fromhex(domain_digest('child-row-v1', row)))
    return h.hexdigest()


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'atlas.sqlite3'
        apply_migrations(self.path)
        self.conn = connect(self.path)
        self.blobs = BlobStore(self.root / 'raw')

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def put(self, model) -> ConflictKind | None:
        if type(model) not in TABLES:
            raise TypeError('unsupported Store.put model')
        model.validate()
        with self.transaction():
            return self._insert(model)

    def _insert(self, model):
        table, keys = TABLES[type(model)]
        values = asdict(model)
        if isinstance(model, RawBlob):
            if len(self.blobs.read(model.blob_sha256)) != model.byte_size:
                raise ValueError('blob size mismatch')
        where = ' AND '.join(f'{key}=?' for key in keys)
        row = self.conn.execute(f'SELECT * FROM {table} WHERE {where}', tuple(values[k] for k in keys)).fetchone()
        if row is not None:
            if dict(row) == values:
                return ConflictKind.IDEMPOTENT_REPEAT
            raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        try:
            self.conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
        except sqlite3.IntegrityError as exc:
            if 'SEAL_VIOLATION' in str(exc):
                raise StoreConflict(ConflictKind.SEAL_VIOLATION) from exc
            if isinstance(model, RunAttemptStart) and ('UNIQUE constraint failed' in str(exc) or 'IMMUTABLE_EVIDENCE' in str(exc)):
                raise StoreConflict(ConflictKind.LOGICAL_KEY_CONFLICT) from exc
            raise
        return None

    def put_blob(self, data: bytes) -> RawBlob:
        model = self.blobs.put(data)
        self.put(model)
        return model

    def put_many(self, models) -> list[ConflictKind | None]:
        models = list(models)
        for model in models:
            if type(model) not in TABLES:
                raise TypeError('unsupported Store.put model')
            model.validate()
        with self.transaction():
            return [self._insert(model) for model in models]

    def put_many_and_seal(self, models, kind: str, aggregate_id: str) -> str:
        if kind not in CHILDREN:
            raise ValueError('unknown seal kind')
        models = list(models)
        for model in models:
            if type(model) not in TABLES:
                raise TypeError('unsupported Store.put model')
            model.validate()
        with self.transaction():
            for model in models:
                self._insert(model)
            return self.seal_current_transaction(kind, aggregate_id)

    def request(self, actor: str, action: str, key: str, payload: object, result_ref: str) -> RequestResult:
        return self.request_write(actor, action, key, payload, lambda _: result_ref)

    def request_write(self, actor: str, action: str, key: str, payload: object,
                      write: Callable[[int], str]) -> RequestResult:
        """Atomically persist a fresh request's evidence and idempotency receipt.

        A retry with the same actor/action/key and payload never invokes ``write``.
        The callback uses this Store connection inside the current transaction and
        returns the durable result reference recorded in ``sys_request_keys``.
        """
        digest = domain_digest('request-payload-v1', payload)
        # Validate human/client identity fields before starting a write transaction.
        RequestResult(actor, action, key, digest, 'pending', 0).validate()
        with self.transaction():
            row = self.conn.execute(
                'SELECT * FROM sys_request_keys WHERE actor_id=? AND action_kind=? AND client_key=?',
                (actor, action, key),
            ).fetchone()
            if row:
                if row['payload_digest'] != digest:
                    raise StoreConflict(ConflictKind.LOGICAL_KEY_CONFLICT)
                return RequestResult(**dict(row))
            previous = self.conn.execute('SELECT max(server_time_us) FROM sys_request_keys').fetchone()[0]
            now = max(time.time_ns() // 1000, (previous + 1) if previous is not None else 0)
            result_ref = write(now)
            model = RequestResult(actor, action, key, digest, result_ref, now)
            model.validate()
            self.conn.execute(
                'INSERT INTO sys_request_keys VALUES (?,?,?,?,?,?)',
                tuple(asdict(model).values()),
            )
            return model

    def child_digest(self, kind: str, aggregate_id: str) -> str:
        return child_digest(self.conn, kind, aggregate_id)

    def seal_current_transaction(self, kind: str, aggregate_id: str) -> str:
        """Seal an aggregate inside an already-open Store transaction."""
        if not self.conn.in_transaction:
            raise RuntimeError('seal_current_transaction requires an active transaction')
        if kind not in CHILDREN:
            raise ValueError('unknown seal kind')
        parent_key, _, _, _ = CHILDREN[kind]
        if not self.conn.execute(
            f'SELECT 1 FROM {kind} WHERE {parent_key}=?',
            (aggregate_id,),
        ).fetchone():
            raise ValueError('unknown seal parent')
        digest = self.child_digest(kind, aggregate_id)
        row = self.conn.execute(
            'SELECT child_set_digest FROM sys_seals '
            'WHERE aggregate_kind=? AND aggregate_id=?',
            (kind, aggregate_id),
        ).fetchone()
        if row:
            if row[0] != digest:
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
            return digest
        self.conn.execute(
            'INSERT INTO sys_seals VALUES (?,?,?)',
            (kind, aggregate_id, digest),
        )
        return digest

    def seal(self, kind: str, aggregate_id: str) -> str:
        with self.transaction():
            return self.seal_current_transaction(kind, aggregate_id)
