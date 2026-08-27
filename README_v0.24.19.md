# Atlas v0.24.19 — Demo Preflight Fix

Built on v0.24.18. This patch does not enable order execution.

Changes:
- fixes the Windows batch parser failure caused by `issue(s)` inside a parenthesized block;
- makes the preflight automatically check `runtime/news_events.json` and the packaged `config/broker_cost_policy.json`;
- makes demo-validator cost-policy validation use Atlas's canonical PAPER_ONLY policy loader, so unmeasured slippage is not falsely required for paper supervision;
- aligns the main preflight/self-check version labels to v0.24.19.

Weekend/closed-market stale ticks and H4/H1/M15 bars remain fail-closed by design. Do not weaken freshness thresholds to make a weekend test pass.

Execution remains locked. No demo enable file is included.
