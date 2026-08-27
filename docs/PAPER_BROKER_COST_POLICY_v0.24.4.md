# Atlas v0.24.4 Paper Broker-Cost Policy

## Scope
This policy is approved for **shadow/paper Supervisor decisions only**. It does not validate live execution costs and cannot unlock the MT5 execution bridge.

## Evidence
Read-only MT5 calibration collected 720 observations per symbol at ~5-second intervals over 60 minutes on 2026-08-21. Slippage was not measurable because no orders were sent.

| Symbol | P50 | P90 | P95 | P99 | Max | Zero samples |
|---|---:|---:|---:|---:|---:|---:|
| EURUSD | 0 | 1 | 1 | 1 | 1 | 362/720 |
| USDJPY | 2 | 3 | 3 | 3 | 3 | 46/720 |
| USDCAD | 1 | 1 | 1 | 1 | 1 | 213/720 |
| XAUUSD | 28 | 42 | 44 | 48.81 | 53 | 0/720 |

## Temporary paper thresholds
The paper gate uses the observed **P95 spread**: EURUSD 1, USDJPY 3, USDCAD 1, XAUUSD 44 points.

Any non-positive spread is treated as unverified and forces WAIT rather than being interpreted as free execution. This is especially important because the calibration observed many zero-spread snapshots on EURUSD and USDCAD.

## Slippage
`execution_validated=false`. The shadow Supervisor uses spread-only cost evidence for paper decisions and tags each review with `PAPER_COST_SPREAD_ONLY_SLIPPAGE_UNMEASURED`. Actual demo-fill slippage must be measured later before any execution-cost policy can be promoted.

## Promotion rule
Permanent execution thresholds require multi-session spread evidence, measured demo-fill slippage, regression validation, and explicit approval. The MT5 execution hard lock is independent of this policy and remains OFF.
