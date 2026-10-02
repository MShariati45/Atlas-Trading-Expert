"""P0-9 hardware baseline helpers.

Audit chaining and external checkpoints live in atlas2.store.audit so there is one
source of truth for tamper-evident audit semantics.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path
import shutil
import sqlite3
import time

from atlas2.core.canonical import canonical_json_text
from atlas2.core.ids import make_id
from atlas2.store.repository import ConflictKind, Store, StoreConflict


def _memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if type(pages) is int and type(page_size) is int:
            return pages * page_size
    except (AttributeError, OSError, ValueError):
        return None
    return None


def collect_hardware_baseline(store_root: str | Path) -> dict:
    usage = shutil.disk_usage(Path(store_root))
    return {
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
    }


def record_hardware_baseline(
    store: Store, *, captured_at_us: int | None = None
) -> tuple[str, dict]:
    if captured_at_us is None:
        captured_at_us = time.time_ns() // 1_000
    content = collect_hardware_baseline(store.root)
    baseline_id = make_id("hwb", "hardware-baseline-v1", content)
    content_json = canonical_json_text(content)
    with store.transaction():
        row = store.conn.execute(
            "SELECT * FROM sys_hardware_baselines WHERE baseline_id=?", (baseline_id,)
        ).fetchone()
        if row is None:
            store.conn.execute(
                "INSERT INTO sys_hardware_baselines VALUES (?,?,?)",
                (baseline_id, captured_at_us, content_json),
            )
        elif row["content_json"] != content_json:
            raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
    return baseline_id, content
