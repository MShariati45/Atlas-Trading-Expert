"""Single holdout-read guard imported by data/labels read paths."""
from __future__ import annotations

from atlas2.core.errors import HoldoutLocked
from atlas2.research.registry import ResearchRegistry
from atlas2.store.repository import Store


def guard_read(
    store: Store,
    *,
    instrument_id: str,
    start_us: int,
    end_us: int,
    route: str,
    actor: str,
    purpose: str,
    grant_ids: tuple[str, ...],
    request_key_prefix: str,
) -> None:
    segments = list(
        store.conn.execute(
            "SELECT segment_id FROM research_holdout_segments "
            "WHERE instrument_id=? AND start_us<? AND end_us>? ORDER BY segment_id",
            (instrument_id, end_us, start_us),
        )
    )
    if not segments:
        return

    if not grant_ids:
        raise HoldoutLocked("protected holdout interval requires a grant")

    grants = {
        row["segment_id"]: row["grant_id"]
        for row in store.conn.execute(
            "SELECT grant_id,segment_id FROM research_holdout_grants "
            f"WHERE grant_id IN ({','.join('?' for _ in grant_ids)})",
            grant_ids,
        )
    }
    required = [row["segment_id"] for row in segments]
    missing = [segment_id for segment_id in required if segment_id not in grants]
    if missing:
        raise HoldoutLocked("missing grant for protected holdout segment")

    registry = ResearchRegistry(store)
    for segment_id in required:
        registry.guard_holdout(
            grants[segment_id],
            actor,
            purpose,
            route,
            start_us,
            end_us,
            f"{request_key_prefix}:{segment_id}",
        )
