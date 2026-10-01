"""Explicit synthetic clock/grid policy for P0-4 tests.

Real broker-server/H4 alignment remains owner Q1 and is deliberately not inferred.
"""

SYNTHETIC_UTC_GRID_V1 = {
    "version": "synthetic-utc-grid-v1",
    "base_timeframe": "M15",
    "alignment": "UTC",
    "target_timeframes": ["H1", "H4", "D1"],
}
