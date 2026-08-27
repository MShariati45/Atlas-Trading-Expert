# Atlas Technical Handoff v0.24.34

v0.24.34 adds the supervised DEMO runtime activation layer on top of v0.24.33.

- `run_supervised_demo_preflight.py`: read-only readiness report.
- `run_supervised_demo_runtime.py`: persistent fail-closed orchestration; observation-only by default.
- The runtime can only reach `DemoExecutionRuntime` when `--allow-execution` is supplied, the broker cost policy is execution/slippage validated, live news is fresh, and all pre-existing hard locks/gates pass.
- No enabled execution switch is shipped.
- Dashboard state now includes `supervised_demo` readiness/candidates.
- REAL/LIVE remains forbidden.
