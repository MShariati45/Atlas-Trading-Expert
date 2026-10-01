"""Small deterministic agreement metrics for P0-5 label studies."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction


DIRECTIONS = ("BULLISH", "BEARISH", "RANGE", "TRANSITION")


def _ppm(value: Fraction) -> int:
    numerator = value.numerator * 1_000_000
    denominator = value.denominator
    quotient, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and quotient % 2):
        quotient += 1
    return quotient


def direction_agreement(pairs: list[tuple[str | None, str | None]]) -> dict:
    usable = [(a, b) for a, b in pairs if a is not None and b is not None]
    for a, b in usable:
        if a not in DIRECTIONS or b not in DIRECTIONS:
            raise ValueError("invalid direction")
    matches = sum(a == b for a, b in usable)
    return {
        "paired_count": len(pairs),
        "usable_count": len(usable),
        "match_count": matches,
        "agreement_ppm": None if not usable else _ppm(Fraction(matches, len(usable))),
    }


def abstention_rate(pairs: list[tuple[str | None, str | None]]) -> dict:
    total_slots = 2 * len(pairs)
    abstentions = sum(value is None for pair in pairs for value in pair)
    return {
        "slot_count": total_slots,
        "abstention_count": abstentions,
        "abstention_ppm": None if not total_slots else _ppm(Fraction(abstentions, total_slots)),
    }


def cohens_kappa(pairs: list[tuple[str | None, str | None]]) -> dict:
    usable = [(a, b) for a, b in pairs if a is not None and b is not None]
    if not usable:
        return {"usable_count": 0, "kappa_ppm": None}
    for a, b in usable:
        if a not in DIRECTIONS or b not in DIRECTIONS:
            raise ValueError("invalid direction")
    n = len(usable)
    observed = Fraction(sum(a == b for a, b in usable), n)
    left = Counter(a for a, _ in usable)
    right = Counter(b for _, b in usable)
    expected = sum(Fraction(left[d] * right[d], n * n) for d in DIRECTIONS)
    if expected == 1:
        return {"usable_count": n, "kappa_ppm": None}
    kappa = (observed - expected) / (1 - expected)
    return {"usable_count": n, "kappa_ppm": _ppm(kappa)}


def anchor_agreement(
    pairs: list[tuple[int | None, int | None]],
    *,
    timeframe_us: int,
    tolerances_bars: tuple[int, ...] = (0, 1, 3),
) -> dict:
    if type(timeframe_us) is not int or timeframe_us <= 0:
        raise ValueError("timeframe_us must be positive int")
    usable = [(a, b) for a, b in pairs if a is not None and b is not None]
    result = {"usable_count": len(usable)}
    for k in tolerances_bars:
        if type(k) is not int or k < 0:
            raise ValueError("tolerance bars must be nonnegative ints")
        matches = sum(abs(a - b) <= k * timeframe_us for a, b in usable)
        result[f"within_{k}_bars_count"] = matches
        result[f"within_{k}_bars_ppm"] = (
            None if not usable else _ppm(Fraction(matches, len(usable)))
        )
    return result
