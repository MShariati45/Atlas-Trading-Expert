from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PricePoint:
    """Provider/timeframe-neutral structural price/time point."""
    price: float
    time: str
