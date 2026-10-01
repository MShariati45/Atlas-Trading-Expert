"""Causal synthetic UTC-grid HTF derivation from visible M15 facts."""
from __future__ import annotations

from atlas2.core.enums import ViewClass
from atlas2.core.taint import combine_taint
from atlas2.model.data import DerivedBar
from atlas2.data.views import MarketView

_US = 1_000_000
_M15_US = 15 * 60 * _US
_FRAME_US = {
    "H1": 60 * 60 * _US,
    "H4": 4 * 60 * 60 * _US,
    "D1": 24 * 60 * 60 * _US,
}
_EXPECTED = {"H1": 4, "H4": 16, "D1": 96}


def utc_grid_open(value_us: int, timeframe: str) -> int:
    if timeframe not in _FRAME_US:
        raise ValueError("timeframe must be H1/H4/D1")
    span = _FRAME_US[timeframe]
    return (value_us // span) * span


def derive_htf(
    view: MarketView,
    instrument_id: str,
    timeframe: str,
    price_side: str,
    open_time_us: int,
    as_of_us: int,
    *,
    view_class: ViewClass = ViewClass.PIT,
) -> DerivedBar:
    if timeframe not in _FRAME_US:
        raise ValueError("timeframe must be H1/H4/D1")
    span = _FRAME_US[timeframe]
    if utc_grid_open(open_time_us, timeframe) != open_time_us:
        raise ValueError("P0-4 synthetic HTF grid is UTC-aligned")

    close_time_us = open_time_us + span
    expected = _EXPECTED[timeframe]
    expected_opens = [open_time_us + i * _M15_US for i in range(expected)]

    constituents = view.bars(
        instrument_id,
        "M15",
        price_side,
        open_time_us,
        close_time_us,
        as_of_us,
        view_class=view_class,
    )
    by_open = {
        visible.fact.open_time_us: visible
        for visible in constituents
        if visible.fact.open_time_us in expected_opens
        and visible.fact.close_time_us == visible.fact.open_time_us + _M15_US
        and visible.fact.close_time_us <= close_time_us
    }
    ordered = [by_open[t] for t in expected_opens if t in by_open]
    if not ordered:
        raise ValueError("no visible M15 constituents")

    partial = as_of_us < close_time_us
    if partial:
        completeness = "PARTIAL_FORMING"
        derived_available = as_of_us
    else:
        completeness = (
            "COMPLETE"
            if len(ordered) == expected
            else "INCOMPLETE_MISSING_INPUT"
        )
        derived_available = max(
            close_time_us,
            max(visible.available_at_us for visible in ordered),
        )

    result = DerivedBar(
        instrument_id,
        timeframe,
        price_side,
        open_time_us,
        close_time_us,
        ordered[0].fact.open,
        max(visible.fact.high for visible in ordered),
        min(visible.fact.low for visible in ordered),
        ordered[-1].fact.close,
        tuple(visible.fact.fact_id for visible in ordered),
        expected,
        len(ordered),
        completeness,
        derived_available,
        int(combine_taint(*(visible.taint for visible in ordered))),
    )
    result.validate()
    return result
