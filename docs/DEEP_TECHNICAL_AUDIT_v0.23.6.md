# Atlas v0.23.6 Adversarial Architecture Audit

Status: GREEN for demo-readiness work, not for live order execution.

## Defects found and corrected
1. Retired legacy dashboard used universal H4/H1 + Fibonacci-first gating that conflicted with the frozen M15-first pattern-specific strategy. The launcher is now hard-disabled.
2. Supervisor could recompute universal H4/H1 alignment and override an upstream pattern-specific HTF permission. A `pattern_policy_resolved` contract now preserves the PatternPolicyGate decision while retaining legacy directional validation only when no pattern policy has been resolved.
3. M15-first launcher passed formal H4 trend rather than H4 `effective_direction`; it now uses the H4 agent's independently confirmed effective direction without rewriting formal history.
4. M15 Impulse/Correction imported `PricePoint` through the H4 agent module; it now imports the shared core type, removing an unnecessary cross-agent dependency.
5. Research/education/learning requirements were previously absent. Added role contracts, trusted-source registry, direct-HTTPS off-hours source monitor, versioned lesson library and persistent correction memory. Research memory cannot mutate live strategy.
6. AI remains disabled by default. Publication monitoring uses no AI API. Optional future AI is event-driven/cached/capped.

## Agent boundaries
- H4: H4 bars/state only.
- H1: H1 bars/state only; explicit cross-timeframe hydration/input rejection already enforced.
- Fibonacci: informational; no entry permission in active profile.
- Each M15 specialist: own pattern geometry/trigger/stop; no specialist-to-specialist imports.
- Coordinator: reads reports, deduplicates, identifies conflicts, selects primary trigger; cannot mutate agents.
- Supervisor: final safety/risk/news/cost/static-zone gates; cannot rewrite analytical state.
- Research/Education Supervisor: source/lesson/correction governance only; cannot approve trades or self-modify strategy.

## Learning governance
Human corrections persist by agent. Trusted-source lessons persist with source URL and evidence hash. Any proposed rule change must be promoted explicitly through code/profile, replay/backtest validation, regression tests and user approval. This prevents silent strategy drift while preserving cumulative institutional memory.

## Verification
- Full production pytest suite: 185 passed.
- Python compileall: passed.
- Pre-demo self-check: passed.
- Active watchlist: EURUSD, USDJPY, USDCAD, XAUUSD.
- GBPUSD absent from active strategy.
- Channel Boundary Rejection is the sole channel strategy.
- Execution bridge locked by default.
- AI disabled by default.

Live execution is not approved by this audit. The next stage is MT5 demo-account readiness and forward validation.
