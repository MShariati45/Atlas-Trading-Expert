from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Optional
import unicodedata

from atlas2.core.enums import AvailabilityBasis
from atlas2.core.ids import make_id, validate_id
from atlas2.core.canonical import ace1_encode, validate_canonical_json_text
from atlas2.core.units import canonical_decimal_text, validate_int64
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
        expected = make_id(
            "fbar",
            "bar-fact-v1",
            {
                "instrument_id": self.instrument_id,
                "timeframe": self.timeframe,
                "price_side": self.price_side,
                "open_time_us": self.open_time_us,
                "close_time_us": self.close_time_us,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "tick_volume": self.tick_volume,
                "real_volume": self.real_volume,
                "spread_points": self.spread_points,
                "spread_semantics": self.spread_semantics,
                "instrument_spec_id": self.instrument_spec_id,
            },
        )
        if self.fact_id != expected:
            raise ValueError("bar fact identity mismatch")


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
        expected = make_id(
            "fqt",
            "quote-fact-v1",
            {
                "instrument_id": self.instrument_id,
                "time_us": self.time_us,
                "source_seq": self.source_seq,
                "bid": self.bid,
                "ask": self.ask,
                "bid_volume": self.bid_volume,
                "ask_volume": self.ask_volume,
                "instrument_spec_id": self.instrument_spec_id,
            },
        )
        if self.fact_id != expected:
            raise ValueError("quote fact identity mismatch")


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


@dataclass(frozen=True, slots=True)
class CalendarScheduleFact:
    fact_id: str
    provider_event_key: str
    currency: str
    title: str
    impact: str
    scheduled_time_us: Optional[int]
    all_day: bool
    reference_period: Optional[str]

    def validate(self) -> None:
        validate_id(self.fact_id, "fcs")
        for value in (self.provider_event_key, self.currency, self.title, self.impact):
            _text(value)
        if not self.currency.isascii():
            raise ValueError("currency must be ASCII")
        if self.scheduled_time_us is not None:
            validate_utc_micros(self.scheduled_time_us)
        if type(self.all_day) is not bool:
            raise TypeError("all_day must be bool")
        if self.reference_period is not None:
            _text(self.reference_period)
        expected = make_id(
            "fcs",
            "calendar-schedule-v1",
            {
                "provider_event_key": self.provider_event_key,
                "currency": self.currency,
                "title": self.title,
                "impact": self.impact,
                "scheduled_time_us": self.scheduled_time_us,
                "all_day": self.all_day,
                "reference_period": self.reference_period,
            },
        )
        if self.fact_id != expected:
            raise ValueError("calendar schedule identity mismatch")


@dataclass(frozen=True, slots=True)
class CalendarValueFact:
    fact_id: str
    provider_event_key: str
    value_kind: str
    value_text: str
    unit: Optional[str]

    def validate(self) -> None:
        validate_id(self.fact_id, "fcv")
        _text(self.provider_event_key)
        if self.value_kind not in {"ACTUAL", "FORECAST", "PREVIOUS", "REVISED_PREVIOUS"}:
            raise ValueError("invalid calendar value_kind")
        _text(self.value_text)
        if canonical_decimal_text(self.value_text) != self.value_text:
            raise ValueError("calendar value_text must be canonical decimal text")
        if self.unit is not None:
            _text(self.unit)
        expected = make_id(
            "fcv",
            "calendar-value-v1",
            {
                "provider_event_key": self.provider_event_key,
                "value_kind": self.value_kind,
                "value_text": self.value_text,
                "unit": self.unit,
            },
        )
        if self.fact_id != expected:
            raise ValueError("calendar value identity mismatch")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    dataset_id: str
    membership_digest: str
    coverage_json: str
    causal_policy_json: str
    htf_policy_json: str
    precedence_policy_json: str
    clock_profile_id: str
    instrument_specs_json: str
    tzdata_version: str
    display_name: str
    built_at_us: int

    def validate(self) -> None:
        validate_id(self.dataset_id, "ds")
        _digest(self.membership_digest)
        for value in (
            self.coverage_json,
            self.causal_policy_json,
            self.htf_policy_json,
            self.precedence_policy_json,
            self.instrument_specs_json,
        ):
            validate_canonical_json_text(value)
        validate_id(self.clock_profile_id, "comp")
        _text(self.tzdata_version)
        _text(self.display_name)
        validate_utc_micros(self.built_at_us)
        identity = {
            "membership_digest": self.membership_digest,
            "coverage": json.loads(self.coverage_json),
            "causal_policy": json.loads(self.causal_policy_json),
            "htf_policy": json.loads(self.htf_policy_json),
            "precedence_policy": json.loads(self.precedence_policy_json),
            "clock_profile_id": self.clock_profile_id,
            "instrument_specs": json.loads(self.instrument_specs_json),
            "tzdata_version": self.tzdata_version,
        }
        expected = make_id("ds", "dataset-version-v1", identity)
        if self.dataset_id != expected:
            raise ValueError("dataset identity mismatch")


@dataclass(frozen=True, slots=True)
class DerivedBar:
    instrument_id: str
    timeframe: str
    price_side: str
    open_time_us: int
    close_time_us: int
    open: int
    high: int
    low: int
    close: int
    constituent_fact_ids: tuple[str, ...]
    expected_constituents: int
    present_constituents: int
    completeness: str
    available_at_us: int
    taint: int = 0

    def validate(self) -> None:
        _instrument(self.instrument_id)
        if self.timeframe not in {"H1", "H4", "D1"}:
            raise ValueError("invalid derived timeframe")
        if self.price_side not in {"BID", "ASK", "MID"}:
            raise ValueError("invalid price_side")
        validate_utc_micros(self.open_time_us)
        validate_utc_micros(self.close_time_us)
        if self.close_time_us <= self.open_time_us:
            raise ValueError("close_time must be after open_time")
        validate_utc_micros(self.available_at_us)
        for value in (self.open, self.high, self.low, self.close):
            validate_int64(value)
        if not (self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise ValueError("invalid OHLC ordering")
        if type(self.constituent_fact_ids) is not tuple:
            raise TypeError("constituent_fact_ids must be tuple")
        for fact_id in self.constituent_fact_ids:
            validate_id(fact_id, "fbar")
        if _nonnegative_int(self.expected_constituents) <= 0:
            raise ValueError("expected_constituents must be positive")
        _nonnegative_int(self.present_constituents)
        if self.present_constituents > self.expected_constituents:
            raise ValueError("present constituents exceed expected")
        if self.present_constituents != len(self.constituent_fact_ids):
            raise ValueError("present count must match constituent ids")
        if self.completeness not in {"COMPLETE", "INCOMPLETE_MISSING_INPUT", "PARTIAL_FORMING"}:
            raise ValueError("invalid completeness")
        _nonnegative(self.taint)


def _nonnegative_int(value: int) -> int:
    validate_int64(value)
    if value < 0:
        raise ValueError("value cannot be negative")
    return value
