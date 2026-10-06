"""Token / context / compute policy: effort tiers, optional usage metrics, budgets, truncation flags.

There are no historical cost constants here. Usage is recorded only when a provider reports it, is
numeric-only (so it cannot carry secrets), and is bounded. Effort selects reasoning depth/model cost; it
never changes permissions, gates or required checks.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .schema import SchemaError, choice, integer, keys, obj

EFFORTS = ("routine", "standard", "deep")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cost_usd_micros", "compute_ms")
BUDGET_FIELDS = {"max_total_tokens": ("input_tokens", "output_tokens"), "max_cost_usd_micros": ("cost_usd_micros",),
                 "max_compute_ms": ("compute_ms",)}
USAGE_MAX = 10**12


def resolve_effort(default: str, override: str | None) -> str:
    """The Owner may override effort for any task; the override never touches permissions or gates."""
    choice(default, "effort", EFFORTS)
    return default if override is None else choice(override, "effort_override", EFFORTS)


def sanitize_usage(raw: Any) -> dict[str, int] | None:
    """Keep only known, bounded, non-negative integer metrics. Anything else is dropped, never stored."""
    if not isinstance(raw, Mapping):
        return None
    clean = {k: raw[k] for k in USAGE_FIELDS if type(raw.get(k)) is int and 0 <= raw[k] <= USAGE_MAX}
    return clean or None


def add_usage(totals: Iterable[Mapping[str, int] | None]) -> dict[str, int]:
    out: dict[str, int] = {}
    for usage in totals:
        for k, v in (usage or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def validate_budget(raw: Any) -> dict[str, int]:
    data = obj(raw, "budget")
    keys(data, "budget", set(), set(BUDGET_FIELDS))
    if not data:
        raise SchemaError("budget: at least one limit is required")
    return {k: integer(v, f"budget.{k}", 1, USAGE_MAX) for k, v in data.items()}


def budget_exceeded(budget: Mapping[str, int] | None, totals: Mapping[str, int]) -> list[str]:
    """Names of exceeded limits. Unreported usage counts as zero (reported honestly as unknown elsewhere)."""
    if not budget:
        return []
    return sorted(limit for limit, fields in BUDGET_FIELDS.items()
                  if limit in budget and sum(totals.get(f, 0) for f in fields) >= budget[limit])


def context_report(**omitted: int) -> dict[str, Any]:
    """Explicit truncation record for a task packet: `{source: omitted_count}`; truncated if anything omitted."""
    dropped = {k: v for k, v in sorted(omitted.items()) if v > 0}
    return {"truncated": bool(dropped), "omitted": dropped}
