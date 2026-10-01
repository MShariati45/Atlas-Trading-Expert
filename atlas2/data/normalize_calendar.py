"""Point-in-time-safe calendar normalization. Unknown history stays UNKNOWN."""
from __future__ import annotations

from atlas2.core.enums import AvailabilityBasis
from atlas2.data.datasets import make_calendar_schedule, make_calendar_value
from atlas2.model.data import FactLink, SourceObservation


def _availability(
    observation: SourceObservation,
    basis: AvailabilityBasis,
    available_at_us: int | None,
) -> int | None:
    if basis is AvailabilityBasis.UNKNOWN:
        if available_at_us is not None:
            raise ValueError("UNKNOWN availability must remain unknown")
        return None
    if basis is AvailabilityBasis.OBSERVED_BY_ATLAS:
        if available_at_us is not None and available_at_us != observation.acquired_at_us:
            raise ValueError("Atlas-observed availability is the acquisition time")
        return observation.acquired_at_us
    if basis is AvailabilityBasis.SOURCE_STAMPED:
        if available_at_us is None:
            raise ValueError("source-stamped availability requires evidence time")
        return available_at_us
    raise ValueError("calendar history supports SOURCE_STAMPED, OBSERVED_BY_ATLAS, or UNKNOWN")


def normalize_schedule(
    row: dict,
    observation: SourceObservation,
    *,
    locator: str,
    normalizer_version_id: str,
    availability_basis: AvailabilityBasis,
    available_at_us: int | None = None,
):
    observation.validate()
    fact = make_calendar_schedule(
        provider_event_key=row["provider_event_key"],
        currency=row["currency"],
        title=row["title"],
        impact=row["impact"],
        scheduled_time_us=row.get("scheduled_time_us"),
        all_day=row.get("all_day", False),
        reference_period=row.get("reference_period"),
    )
    link = FactLink(
        fact.fact_id,
        observation.obs_id,
        locator,
        normalizer_version_id,
        _availability(observation, availability_basis, available_at_us),
        availability_basis,
        row.get("quality_flags", 0),
    )
    link.validate()
    return fact, link


def normalize_value(
    row: dict,
    observation: SourceObservation,
    *,
    locator: str,
    normalizer_version_id: str,
    availability_basis: AvailabilityBasis,
    available_at_us: int | None = None,
):
    observation.validate()
    fact = make_calendar_value(
        provider_event_key=row["provider_event_key"],
        value_kind=row["value_kind"],
        value_text=row["value_text"],
        unit=row.get("unit"),
    )
    link = FactLink(
        fact.fact_id,
        observation.obs_id,
        locator,
        normalizer_version_id,
        _availability(observation, availability_basis, available_at_us),
        availability_basis,
        row.get("quality_flags", 0),
    )
    link.validate()
    return fact, link
