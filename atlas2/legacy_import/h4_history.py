"""Conditional read-only import of copied legacy H4 impulse-history SQLite data."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

from atlas2.core.canonical import canonical_json_text, domain_digest
from atlas2.core.ids import make_id, validate_id
from atlas2.core.taint import Taint
from atlas2.core.units import price_to_int
from atlas2.labels.submit import LabelSubmissionService
from atlas2.legacy_import.checkpoint import sha256_file
from atlas2.store.repository import ConflictKind, Store, StoreConflict

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_REQUIRED_MAPPING_KEYS = frozenset({
    "table", "source_key", "actor", "instrument", "trend", "confidence",
    "impulse_start_price", "impulse_start_side",
    "impulse_end_price", "impulse_end_side",
    "correction_price", "correction_side",
    "owner_values", "engine_values", "trend_map",
    "price_mode", "price_digits", "market_price_side",
})


@dataclass(frozen=True, slots=True)
class LegacySource:
    source_id: str
    source_sha256: str
    byte_size: int
    basename: str
    schema_digest: str
    mapping_json: str


@dataclass(frozen=True, slots=True)
class LegacyH4Record:
    source_key: str
    actor_kind: str
    instrument_id: str
    trend: str
    confidence: int
    anchors: tuple[dict, ...]
    source_row_digest: str


@dataclass(frozen=True, slots=True)
class LegacyImportResult:
    source: LegacySource
    imported_group_ids: tuple[str, ...]
    unchanged_source_sha256: str


def _identifier(value: str) -> str:
    if type(value) is not str or not _IDENT.fullmatch(value):
        raise ValueError("legacy mapping identifiers must be simple SQLite identifiers")
    return value


def validate_mapping(mapping: object) -> dict:
    if type(mapping) is not dict or set(mapping) != _REQUIRED_MAPPING_KEYS:
        raise ValueError("legacy H4 mapping has wrong keys")
    result = dict(mapping)
    for key in (
        "table", "source_key", "actor", "instrument", "trend", "confidence",
        "impulse_start_price", "impulse_start_side",
        "impulse_end_price", "impulse_end_side",
    ):
        _identifier(result[key])
    for key in ("correction_price", "correction_side"):
        if result[key] is not None:
            _identifier(result[key])
    for key in ("owner_values", "engine_values"):
        values = result[key]
        if type(values) is not list or not values or any(type(v) is not str or not v for v in values):
            raise ValueError(f"{key} must be a nonempty string list")
        if len(values) != len(set(values)):
            raise ValueError(f"{key} must be unique")
    if set(result["owner_values"]) & set(result["engine_values"]):
        raise ValueError("owner/engine actor values must not overlap")
    trend_map = result["trend_map"]
    if type(trend_map) is not dict or not trend_map:
        raise ValueError("trend_map must be a nonempty dict")
    for raw, normalized in trend_map.items():
        if type(raw) is not str or normalized not in {"BULLISH", "BEARISH", "RANGE", "TRANSITION"}:
            raise ValueError("invalid trend mapping")
    if result["price_mode"] not in {"SCALED_INT", "SQLITE_REAL_DECIMAL_V1"}:
        raise ValueError("invalid legacy price mode")
    if result["market_price_side"] not in {"BID", "ASK", "MID"}:
        raise ValueError("market_price_side must be BID/ASK/MID")
    digits = result["price_digits"]
    if type(digits) is not int or not 0 <= digits <= 12:
        raise ValueError("price_digits must be 0..12")
    if (result["correction_price"] is None) != (result["correction_side"] is None):
        raise ValueError("correction price/side columns must both be set or both be null")
    columns = _selected_columns(result)
    if len(columns) != len(set(columns)):
        raise ValueError("legacy mapping columns must be distinct")
    return result


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _schema_inventory(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise ValueError("mapped legacy table does not exist")
    return [
        {
            "name": row["name"],
            "type": row["type"],
            "notnull": row["notnull"],
            "pk": row["pk"],
        }
        for row in rows
    ]


def _selected_columns(mapping: dict) -> list[str]:
    columns = [
        mapping["source_key"], mapping["actor"], mapping["instrument"],
        mapping["trend"], mapping["confidence"],
        mapping["impulse_start_price"], mapping["impulse_start_side"],
        mapping["impulse_end_price"], mapping["impulse_end_side"],
    ]
    if mapping["correction_price"] is not None:
        columns.extend([mapping["correction_price"], mapping["correction_side"]])
    return columns


def inspect_source(path: str | Path, mapping: object) -> LegacySource:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(target)
    normalized = validate_mapping(mapping)
    before = sha256_file(target)
    size = target.stat().st_size
    conn = _open_read_only(target)
    try:
        schema = _schema_inventory(conn, normalized["table"])
        names = {item["name"] for item in schema}
        missing = [column for column in _selected_columns(normalized) if column not in names]
        if missing:
            raise ValueError("legacy mapping columns not present: " + ",".join(sorted(missing)))
        schema_digest = domain_digest("legacy-sqlite-schema-v1", schema)
    finally:
        conn.close()
    after = sha256_file(target)
    if before != after:
        raise RuntimeError("legacy source changed during read-only inspection")
    mapping_json = canonical_json_text(normalized)
    source_id = make_id("lsrc", "legacy-import-source-v1", {
        "source_kind": "H4_IMPULSE_HISTORY",
        "source_sha256": before,
        "byte_size": size,
        "schema_digest": schema_digest,
        "mapping": normalized,
    })
    return LegacySource(source_id, before, size, target.name, schema_digest, mapping_json)


def _required_text_value(row: sqlite3.Row, column: str, label: str) -> str:
    value = row[column]
    if value is None:
        raise ValueError(f"legacy {label} cannot be NULL")
    if type(value) is not str:
        raise ValueError(f"legacy {label} must be SQLite TEXT")
    if not value:
        raise ValueError(f"legacy {label} cannot be empty")
    return value


def _price(value, mapping: dict) -> int:
    if mapping["price_mode"] == "SCALED_INT":
        if type(value) is not int:
            raise ValueError("SCALED_INT legacy price must be SQLite INTEGER")
        return value
    if type(value) is bool or value is None:
        raise ValueError("legacy price is missing/invalid")
    if type(value) is float:
        text = repr(value)
    elif type(value) in {int, str}:
        text = str(value)
    else:
        raise ValueError("unsupported legacy SQLite price type")
    return price_to_int(text, mapping["price_digits"])


def read_records(path: str | Path, mapping: object) -> tuple[LegacySource, tuple[LegacyH4Record, ...]]:
    target = Path(path)
    normalized = validate_mapping(mapping)
    source = inspect_source(target, normalized)
    columns = _selected_columns(normalized)
    quoted_columns = ",".join(f'"{column}"' for column in columns)
    table = normalized["table"]
    conn = _open_read_only(target)
    records = []
    try:
        rows = conn.execute(
            f'SELECT {quoted_columns} FROM "{table}" ORDER BY "{normalized["source_key"]}"'
        ).fetchall()
        seen = set()
        for row in rows:
            source_key = _required_text_value(row, normalized["source_key"], "source_key")
            if source_key in seen:
                raise ValueError("legacy source_key must be unique")
            seen.add(source_key)
            actor_raw = _required_text_value(row, normalized["actor"], "actor")
            if actor_raw in normalized["owner_values"]:
                actor_kind = "OWNER"
            elif actor_raw in normalized["engine_values"]:
                actor_kind = "ENGINE"
            else:
                raise ValueError(f"unmapped legacy actor value: {actor_raw}")
            trend_raw = _required_text_value(row, normalized["trend"], "trend")
            try:
                trend = normalized["trend_map"][trend_raw]
            except KeyError as exc:
                raise ValueError(f"unmapped legacy trend value: {trend_raw}") from exc
            confidence = row[normalized["confidence"]]
            if type(confidence) is not int or not 1 <= confidence <= 5:
                raise ValueError("legacy confidence must be integer 1..5")
            anchors = [
                {
                    "role": "IMPULSE_START",
                    "price": _price(row[normalized["impulse_start_price"]], normalized),
                    "side": _required_text_value(row, normalized["impulse_start_side"], "impulse_start_side").upper(),
                },
                {
                    "role": "IMPULSE_END",
                    "price": _price(row[normalized["impulse_end_price"]], normalized),
                    "side": _required_text_value(row, normalized["impulse_end_side"], "impulse_end_side").upper(),
                },
            ]
            if normalized["correction_price"] is not None:
                price_value = row[normalized["correction_price"]]
                side_value = row[normalized["correction_side"]]
                if price_value is not None or side_value is not None:
                    if price_value is None or side_value is None:
                        raise ValueError("partial correction anchor in legacy row")
                    anchors.append({
                        "role": "CORRECTION_EXTREME",
                        "price": _price(price_value, normalized),
                        "side": _required_text_value(row, normalized["correction_side"], "correction_side").upper(),
                    })
            for anchor in anchors:
                if anchor["side"] not in {"HIGH", "LOW"}:
                    raise ValueError("legacy anchor side must map to HIGH/LOW")
            row_semantic = {
                "source_key": source_key,
                "actor_kind": actor_kind,
                "instrument_id": _required_text_value(row, normalized["instrument"], "instrument"),
                "trend": trend,
                "confidence": confidence,
                "anchors": anchors,
            }
            records.append(LegacyH4Record(
                source_key, actor_kind, row_semantic["instrument_id"], trend,
                confidence, tuple(anchors),
                domain_digest("legacy-h4-row-v1", row_semantic),
            ))
    finally:
        conn.close()
    after = sha256_file(target)
    if after != source.source_sha256:
        raise RuntimeError("legacy source changed during read-only record scan")
    return source, tuple(records)


def _unique_anchor_time(
    store: Store, *, dataset_id: str, instrument_id: str, timeframe: str,
    market_price_side: str, side: str, price: int, cutoff_us: int,
) -> int | None:
    column = "high" if side == "HIGH" else "low"
    rows = store.conn.execute(
        f"""SELECT DISTINCT b.open_time_us
            FROM data_dataset_membership m
            JOIN data_bar_facts b ON b.fact_id=m.fact_id
            WHERE m.dataset_id=? AND m.fact_kind='BAR'
              AND b.instrument_id=? AND b.timeframe=? AND b.price_side=?
              AND b.{column}=? AND b.close_time_us<=?
            ORDER BY b.open_time_us""",
        (dataset_id, instrument_id, timeframe, market_price_side, price, cutoff_us),
    ).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def _register_source(store: Store, source: LegacySource) -> None:
    row = store.conn.execute(
        "SELECT * FROM legacy_import_sources WHERE source_id=?", (source.source_id,)
    ).fetchone()
    expected = {
        "source_id": source.source_id,
        "source_kind": "H4_IMPULSE_HISTORY",
        "source_sha256": source.source_sha256,
        "byte_size": source.byte_size,
        "basename": source.basename,
        "schema_digest": source.schema_digest,
        "mapping_json": source.mapping_json,
    }
    if row is None:
        store.conn.execute(
            "INSERT INTO legacy_import_sources VALUES (?,?,?,?,?,?,?)",
            tuple(expected.values()),
        )
    elif dict(row) != expected:
        raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)


def import_records(
    store: Store,
    path: str | Path,
    mapping: object,
    *,
    task_by_source_key: dict[str, str],
    infer_unique_price_matches: bool = False,
) -> LegacyImportResult:
    target = Path(path)
    source, records = read_records(target, mapping)
    normalized = validate_mapping(mapping)
    submitter = LabelSubmissionService(store)
    group_ids = []
    validated = []
    for record in records:
        try:
            task_id = task_by_source_key[record.source_key]
        except KeyError as exc:
            raise ValueError(f"no label task mapped for legacy row {record.source_key}") from exc
        validate_id(task_id, "ltask")
        task = store.conn.execute(
            """SELECT s.instrument_id,s.timeframe,s.dataset_id,s.visible_data_cutoff_us
               FROM label_tasks t JOIN label_task_seeds s ON s.seed_id=t.seed_id
               WHERE t.task_id=?""",
            (task_id,),
        ).fetchone()
        if task is None:
            raise ValueError("mapped legacy label task does not exist")
        if task["instrument_id"] != record.instrument_id:
            raise ValueError("legacy row instrument does not match mapped label task")
        validated.append((record, task_id, task))

    with store.transaction():
        _register_source(store, source)

    for record, task_id, task in validated:
        existing_import = store.conn.execute(
            "SELECT * FROM legacy_import_rows WHERE source_id=? AND source_key=?",
            (source.source_id, record.source_key),
        ).fetchone()
        if existing_import is not None:
            if (
                existing_import["source_row_digest"] != record.source_row_digest
                or existing_import["actor_kind"] != record.actor_kind
                or existing_import["task_id"] != task_id
            ):
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
            if not store.conn.execute(
                "SELECT 1 FROM label_groups WHERE group_id=?",
                (existing_import["group_id"],),
            ).fetchone():
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
            group_ids.append(existing_import["group_id"])
            continue
        anchor_specs = []
        inferred = False
        for anchor in record.anchors:
            bar_time = None
            if infer_unique_price_matches:
                bar_time = _unique_anchor_time(
                    store, dataset_id=task["dataset_id"],
                    instrument_id=record.instrument_id,
                    timeframe=task["timeframe"], market_price_side=normalized["market_price_side"],
                    side=anchor["side"], price=anchor["price"],
                    cutoff_us=task["visible_data_cutoff_us"],
                )
            if bar_time is None:
                time_status = "UNKNOWN_LEGACY"
            else:
                time_status = "INFERRED_RECONSTRUCTION"
                inferred = True
            anchor_specs.append({
                "role": anchor["role"],
                "bar_open_time_us": bar_time,
                "side": anchor["side"],
                "price": anchor["price"],
                "confirmation_time_us": None,
                "time_status": time_status,
            })
        mode = "LEGACY_IMPORT" if record.actor_kind == "OWNER" else "ENGINE"
        labeler = "legacy:owner" if record.actor_kind == "OWNER" else "legacy:engine"
        extra_taint = int(Taint.INFERRED_RECONSTRUCTION) if (record.actor_kind == "ENGINE" or inferred) else 0
        group = submitter.submit(
            task_id=task_id,
            labeler_id=labeler,
            request_key=f"legacy:{source.source_id}:{record.source_key}",
            kind="INTERPRETATIONS",
            label_mode=mode,
            interpretations=[{
                "rank": 1,
                "probability_ppm": None,
                "trend": record.trend,
                "confidence": record.confidence,
                "correction_depth_ppm": None,
                "correction_class": None,
                "reason": f"legacy-source:{source.source_id}",
                "anchors": anchor_specs,
            }],
            exposure_attestation="LEGACY_SOURCE_READ_ONLY",
            system_exposure_flag=False,
            extra_taint=extra_taint,
        )
        import_row_id = make_id("lrow", "legacy-import-row-v1", {
            "source_id": source.source_id,
            "source_key": record.source_key,
            "source_row_digest": record.source_row_digest,
            "task_id": task_id,
            "group_id": group.group_id,
        })
        with store.transaction():
            row = store.conn.execute(
                "SELECT * FROM legacy_import_rows WHERE source_id=? AND source_key=?",
                (source.source_id, record.source_key),
            ).fetchone()
            expected = {
                "import_row_id": import_row_id,
                "source_id": source.source_id,
                "source_key": record.source_key,
                "source_row_digest": record.source_row_digest,
                "actor_kind": record.actor_kind,
                "task_id": task_id,
                "group_id": group.group_id,
            }
            if row is None:
                store.conn.execute(
                    "INSERT INTO legacy_import_rows VALUES (?,?,?,?,?,?,?)",
                    tuple(expected.values()),
                )
            elif dict(row) != expected:
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        group_ids.append(group.group_id)
    after = sha256_file(target)
    if after != source.source_sha256:
        raise RuntimeError("legacy source changed during import")
    return LegacyImportResult(source, tuple(group_ids), after)
