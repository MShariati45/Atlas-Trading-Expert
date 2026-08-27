# Atlas v0.24.22 - Multi-Account Trader Access + Demo Execution Preparation

This checkpoint upgrades the staging model so one Trader identity may have multiple independently isolated MT5 accounts while remaining strictly read-only.

## Added
- Owner-only `1 Trader -> N MT5 accounts` assignment/unassignment.
- Trader account switching validation that only permits assigned accounts.
- Read-only per-account summary model for the Trader portal.
- Independent account execution lifecycle:
  `CONNECTED -> OBSERVATION -> DEMO_AUTHORIZED -> EXECUTION_ENABLED`.
- Connection never implies order authorization.
- Each MT5 account retains separate worker, risk, execution state, reporting, and history.

## Safety
- Traders cannot change risk, strategy, execution, or account assignments.
- Admins cannot create/attach/remove customer accounts under the current approved governance model.
- Demo authorization cannot skip states and fails closed back to OBSERVATION.
- No LIVE-money enablement is added by this release.
- Existing MT5 execution hard lock remains unchanged.

## Next operational gate
Run broker spread observation during a fresh market, then rerun the demo preflight. Slippage remains unvalidated until controlled DEMO_ONLY fills are intentionally enabled later.
