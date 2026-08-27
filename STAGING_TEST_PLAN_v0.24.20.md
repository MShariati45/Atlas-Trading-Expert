# Atlas Staging End-to-End Test Plan

## Public landing page
- Desktop/mobile layout
- Menu behavior
- Request Information validation
- Lead stored once
- Spam/rate-limit behavior
- Client Login does not create public registration

## Roles and users
- Owner can create/suspend users and attach accounts
- Admin cannot create users or attach customer accounts
- Trader sees only assigned accounts
- Trader cannot change risk, strategy, execution, research, or other-user data
- Suspended web access does not silently stop MT5 trading account management

## Trading demo chain
- H4 owner confirmation/edit
- M15 specialist signal
- Coordinator confluence
- Supervisor gates
- News/cost/spread checks
- 0.5% per-trade risk
- max 2 trades/day
- 1% daily cap
- one open trade per symbol
- 2R target baseline
- duplicate-order rejection
- Friday rules
- emergency stop

## Reports and audit
- Open/closed trade states
- R and USD P/L
- Account-specific report scoping
- CSV/PDF permissions
- H4 edits and supervisor decisions logged
- Lead and user security events logged

## Failure drills
- MT5 disconnect
- stale quotes
- stale/missing news
- invalid broker cost policy
- account worker crash
- duplicate signal/order
- unauthorized Trader endpoint request
- bad password/repeated login attempts

## Launch rule
No live-money mode. Controlled demo-only unlock is allowed only after every mandatory safety gate passes and the execution path is retested with fresh market data.
