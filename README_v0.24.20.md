# Atlas v0.24.20 - Staging Integration Scaffold

Purpose: integrate the approved Aug 22, 2026 Atlas staging architecture without enabling real-money or demo order execution.

## Added
- Approved OWNER / ADMIN / TRADER role model. Owner alone creates users and attaches customer accounts. Trader is read-only for assigned accounts.
- Local Request Information lead intake with append-only staging lead store. Lead submission never creates a user or grants application access.
- Responsive public landing-page scaffold using the approved Concept A Atlas branding direction.
- Local staging web runner for landing-page/lead-flow testing. Client Login deliberately remains unavailable until hardened authentication is implemented.
- Staging readiness check covering landing page, lead store, role model, H4 approval gate, execution lock, broker cost policy, and live-news runtime presence.
- Version consistency updated to 0.24.20 for the new staging slice.

## Safety
- Demo execution remains LOCKED.
- Real-money execution remains out of scope.
- Missing live-news runtime continues to fail closed.
- Broker cost policy remains required.
- No AI/API calls are required for landing-page lead intake, role checks, H4 approvals, risk controls, or staging readiness.

## Windows quick start
1. Extract the package to a new folder.
2. Run `run_staging_readiness.bat`.
3. For local landing-page testing only, run `run_staging_web.bat` and open `http://127.0.0.1:8080`.
4. Do not attempt demo execution until the market-open preflight is green and the dedicated demo unlock package is explicitly produced.

## Current known external gate
`runtime/news_events.json` is intentionally not fabricated. It must be populated from a trusted/licensed or approved official-calendar pipeline before market-open demo supervision can become ready.

## Regression
257 tests pass in this package.
