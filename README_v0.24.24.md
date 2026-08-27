# Atlas v0.24.24 - Adaptive Spread Guard

This checkpoint implements the approved broker-cost philosophy: Atlas learns a normal spread baseline per symbol and broad UTC liquidity session, while rejecting temporary spread shocks as baseline training data.

## Entry behavior
- NORMAL: spread is within recent symbol/session expectations.
- ELEVATED: spread is above the normal band; Atlas records caution but may continue if other gates pass.
- BLOCK: current spread is roughly 2x+ normal / statistically abnormal, or spread consumes too much of the structural stop distance.
- UNAVAILABLE: insufficient baseline evidence -> fail closed when adaptive spread is required.

The structural pattern still defines the stop. Spread is included in viability/risk checks; Atlas does not widen a bad stop simply to accommodate an abnormal broker spread.

The baseline is local/deterministic, uses zero AI calls, does not send orders, and never rewrites policy thresholds automatically.
