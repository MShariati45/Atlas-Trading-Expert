from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import unicodedata

from atlas2.core.enums import AvailabilityBasis
from atlas2.core.ids import validate_id
from atlas2.core.canonical import ace1_encode
from atlas2.core.units import validate_int64
from atlas2.core.time import validate_utc_micros


def _text(value: str) -> None:
    if type(value) is not str or not value:
        raise ValueError("nonempty text required")
    if value != unicodedata.normalize("NFC", value):
        raise ValueError("text must be NFC-normalized before storage")
    ace1_encode(value)


def _digest(value: str) -> None:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("blob_sha256 must be lowercase sha256 hex")


def _nonnegative(value: int) -> None:
    if validate_int64(value) < 0:
        raise ValueError("value cannot be negative")


def _instrument(value: str) -> None:
    _text(value)
    if not value.isascii():
        raise ValueError("instrument_id must be ASCII")


@dataclass(frozen=True, slots=True)
class RawBlob:
    blob_sha256: str
    byte_size: int

    def validate(self) -> None:
        _digest(self.blob_sha256)
        validate_int64(self.byte_size)
        if self.byte_size <= 0:
            raise ValueError("byte_size must be positive int")


@dataclass(frozen=True, slots=True)
class SourceObservation:
    obs_id: str
    blob_sha256: str
    source_id: str
    source_version: str
    acquisition_kind: str
    acquired_at_us: int
    clock_profile_id: str

    def validate(self) -> None:
        validate_id(self.obs_id, "obs")
        _digest(self.blob_sha256)
        _text(self.source_id)
        _text(self.source_version)
        _text(self.acquisition_kind)
        if self.acquisition_kind not in {"HISTORICAL_EXPORT", "LIVE_POLL", "MANUAL_IMPORT"}:
            raise ValueError("invalid acquisition_kind")
        if type(self.acquired_at_us) is not int:
            raise TypeError("acquired_at_us must be int")
        validate_utc_micros(self.acquired_at_us)
        validate_id(self.clock_profile_id, "comp")


@dataclass(frozen=True, slots=True)
class BarFact:
    fact_id: str
    instrument_id: str
    timeframe: str
    price_side: str
    open_time_us: int
    close_time_us: int
    open: int
    high: int
    low: int
    close: int
    tick_volume: int
    real_volume: Optional[int]
    spread_points: Optional[int]
    spread_semantics: Optional[str]
    instrument_spec_id: str

    def validate(self) -> None:
        validate_id(self.fact_id, "fbar")
        validate_id(self.instrument_spec_id)
        _instrument(self.instrument_id)
        _text(self.timeframe)
        _text(self.price_side)
        validate_utc_micros(self.open_time_us)
        validate_utc_micros(self.close_time_us)
        for value in (self.open, self.high, self.low, self.close):
            validate_int64(value)
        _nonnegative(self.tick_volume)
        for value in (self.real_volume, self.spread_points):
            if value is not None:
                _nonnegative(value)
        if self.spread_semantics is not None:
            _text(self.spread_semantics)
        if self.timeframe not in {"M1", "M5", "M15", "H1", "H4", "D1"}:
            raise ValueError("invalid timeframe")
        if self.price_side not in {"BID", "ASK", "MID"}:
            raise ValueError("invalid price_side")
        if self.close_time_us <= self.open_time_us:
            raise ValueError("close_time must be after open_time")
        if not (self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise ValueError("invalid OHLC ordering")


@dataclass(frozen=True, slots=True)
class QuoteFact:
    fact_id: str
    instrument_id: str
    time_us: int
    source_seq: Optional[int]
    bid: int
    ask: int
    bid_volume: Optional[int]
    ask_volume: Optional[int]
    instrument_spec_id: str

    def validate(self) -> None:
        validate_id(self.fact_id, "fqt")
        validate_id(self.instrument_spec_id)
        _instrument(self.instrument_id)
        validate_utc_micros(self.time_us)
        for value in (self.bid, self.ask):
            validate_int64(value)
        for value in (self.source_seq, self.bid_volume, self.ask_volume):
            if value is not None:
                _nonnegative(value)
        if self.ask < self.bid:
            raise ValueError("crossed quote")


@dataclass(frozen=True, slots=True)
class FactLink:
    fact_id: str
    obs_id: str
    locator: str
    normalizer_version_id: str
    available_at_us: Optional[int]
    availability_basis: AvailabilityBasis
    quality_flags: int = 0

    def validate(self) -> None:
        validate_id(self.fact_id, ("fbar", "fqt", "fcs", "fcv"))
        validate_id(self.obs_id, "obs")
        validate_id(self.normalizer_version_id, "comp")
        _text(self.locator)
        if not isinstance(self.availability_basis, AvailabilityBasis):
            raise ValueError("availability_basis must be AvailabilityBasis")
        if self.available_at_us is not None:
            validate_utc_micros(self.available_at_us)
        if self.availability_basis is AvailabilityBasis.UNKNOWN:
            if self.available_at_us is not None:
                raise ValueError("UNKNOWN availability must not carry available_at")
        elif self.available_at_us is None:
            raise ValueError("known availability requires available_at_us")
        _nonnegative(self.quality_flags)


@dataclass(frozen=True, slots=True)
class DatasetMembership:
    dataset_id: str
    fact_kind: str
    fact_id: str
    obs_id: str
    locator: str

    def validate(self) -> None:
        validate_id(self.dataset_id, "ds")
        validate_id(self.fact_id, ("fbar", "fqt", "fcs", "fcv"))
        validate_id(self.obs_id, "obs")
        _text(self.fact_kind)
        prefix_by_kind = {
            "BAR": "fbar",
            "QUOTE": "fqt",
            "CALENDAR_SCHEDULE": "fcs",
            "CALENDAR_VALUE": "fcv",
        }
        try:
            expected_prefix = prefix_by_kind[self.fact_kind]
        except KeyError as exc:
            raise ValueError("invalid fact_kind") from exc
        validate_id(self.fact_id, expected_prefix)
        _text(self.locator)
