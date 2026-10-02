"""Minimal P0 control arm: DATA_QUALITY is the only required gate."""
from __future__ import annotations

def decide(data_quality_outcome: str) -> tuple[str, tuple[str, ...]]:
    if data_quality_outcome == "PASS":
        return "ACCEPT", ()
    if data_quality_outcome == "FAIL":
        return "REJECT", ("DATA_QUALITY_FAIL",)
    if data_quality_outcome == "ERROR":
        return "ERROR", ("DATA_QUALITY_ERROR",)
    return "ABSTAIN", (f"DATA_QUALITY_{data_quality_outcome}",)
