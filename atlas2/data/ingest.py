"""Raw source registration for the P0-4 data spine."""
from __future__ import annotations

from atlas2.core.ids import make_id
from atlas2.model.data import SourceObservation
from atlas2.store.repository import Store


def ingest_source_bytes(
    store: Store,
    data: bytes,
    *,
    source_id: str,
    source_version: str,
    acquisition_kind: str,
    acquired_at_us: int,
    clock_profile_id: str,
) -> SourceObservation:
    blob = store.put_blob(data)
    identity = {
        "blob_sha256": blob.blob_sha256,
        "source_id": source_id,
        "source_version": source_version,
        "acquisition_kind": acquisition_kind,
        "acquired_at_us": acquired_at_us,
        "clock_profile_id": clock_profile_id,
    }
    model = SourceObservation(
        make_id("obs", "source-observation-v1", identity),
        blob.blob_sha256,
        source_id,
        source_version,
        acquisition_kind,
        acquired_at_us,
        clock_profile_id,
    )
    model.validate()
    store.put(model)
    return model
