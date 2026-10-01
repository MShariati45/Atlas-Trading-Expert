"""Pure broker-export normalization. No MetaTrader SDK import is allowed in P0."""
from __future__ import annotations

from atlas2.core.enums import AvailabilityBasis, DataQualityFlag
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import price_to_int, validate_int64
from atlas2.data.datasets import make_bar_fact, make_quote_fact
from atlas2.model.data import FactLink, SourceObservation


def normalize_bar(
    row: dict,
    observation: SourceObservation,
    *,
    locator: str,
    normalizer_version_id: str,
    instrument_id: str,
    timeframe: str,
    price_side: str,
    price_digits: int,
    instrument_spec_id: str,
    publication_lag_us: int = 0,
):
    observation.validate()
    validate_int64(publication_lag_us)
    if publication_lag_us < 0:
        raise ValueError("publication lag cannot be negative")
    open_time_us = validate_utc_micros(row["open_time_us"])
    close_time_us = validate_utc_micros(row["close_time_us"])
    fact = make_bar_fact(
        instrument_id=instrument_id,
        timeframe=timeframe,
        price_side=price_side,
        open_time_us=open_time_us,
        close_time_us=close_time_us,
        open=price_to_int(row["open"], price_digits),
        high=price_to_int(row["high"], price_digits),
        low=price_to_int(row["low"], price_digits),
        close=price_to_int(row["close"], price_digits),
        tick_volume=row.get("tick_volume", 0),
        real_volume=row.get("real_volume"),
        spread_points=row.get("spread_points"),
        spread_semantics=row.get("spread_semantics"),
        instrument_spec_id=instrument_spec_id,
    )
    link = FactLink(
        fact.fact_id,
        observation.obs_id,
        locator,
        normalizer_version_id,
        close_time_us + publication_lag_us,
        AvailabilityBasis.BAR_CLOSE_RULE,
        row.get("quality_flags", 0),
    )
    link.validate()
    return fact, link


def normalize_quote(
    row: dict,
    observation: SourceObservation,
    *,
    locator: str,
    normalizer_version_id: str,
    instrument_id: str,
    price_digits: int,
    instrument_spec_id: str,
    availability_basis: AvailabilityBasis,
    available_at_us: int | None,
):
    observation.validate()
    source_seq = row.get("source_seq")
    fact = make_quote_fact(
        instrument_id=instrument_id,
        time_us=validate_utc_micros(row["time_us"]),
        source_seq=source_seq,
        bid=price_to_int(row["bid"], price_digits),
        ask=price_to_int(row["ask"], price_digits),
        bid_volume=row.get("bid_volume"),
        ask_volume=row.get("ask_volume"),
        instrument_spec_id=instrument_spec_id,
    )
    if availability_basis is AvailabilityBasis.OBSERVED_BY_ATLAS:
        if available_at_us is not None and available_at_us != observation.acquired_at_us:
            raise ValueError("Atlas-observed quote availability is the acquisition time")
        available_at_us = observation.acquired_at_us
    quality_flags = row.get("quality_flags", 0)
    if source_seq is None:
        quality_flags |= int(DataQualityFlag.MULTIPLICITY_UNKNOWABLE)
    link = FactLink(
        fact.fact_id,
        observation.obs_id,
        locator,
        normalizer_version_id,
        available_at_us,
        availability_basis,
        quality_flags,
    )
    link.validate()
    return fact, link
