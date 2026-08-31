# Atlas Trading Expert --- Frozen Checkpoint

**Checkpoint date:** 2026-08-30\
**Status:** END-OF-DAY FROZEN\
**Environment:** DEMO / STAGING ONLY\
**Real money:** DISABLED / FORBIDDEN

## 1. Purpose

This checkpoint freezes the Atlas Trading Expert state at the end of
today's work. Future work must continue from this checkpoint and must
not redesign or replace previously frozen components unless the owner
explicitly changes a requirement.

## 2. Core Safety Boundary

-   Real-money trading remains disabled.
-   Atlas is operating in DEMO / STAGING.
-   The web/read-model layer must remain read-only with respect to MT5
    execution.
-   No Research Laboratory page or research endpoint may become an
    execution transport.
-   Trading promotion remains controlled by owner approval.
-   Existing backups and checkpoints must not be deleted.

## 3. Approved Trading Watchlist

Frozen symbols: - XAUUSD - EURUSD - USDCAD - USDJPY

The established Watchlist visual design and Market Intelligence design
are frozen. Do not redesign them from scratch.

## 4. Trading Logic --- Frozen

Hierarchy: 1. H4 strategic direction 2. H1 counter-structure requirement
3. M15 execution confirmation

Retained M15 specialists: - Triangles / Wedges - Flags / Pennants -
Double / Multiple Tops and Bottoms - Head & Shoulders / Inverse Head &
Shoulders - Channel Boundary Rejection - M15 Impulse & Correction

Removed: - Original Channel Breakout

Fibonacci: - Measurement only - Not an entry gate

## 5. Risk Rules --- Frozen

-   Daily risk cap: 1.0%
-   Maximum trades per day: 2
-   Risk per trade: 0.5%
-   Maximum one open trade per symbol
-   Target: 2R
-   Break-even management around +1.4R
-   New entries Monday through Thursday only
-   No new Friday trades
-   Positions must be closed before Friday market close

## 6. Owner Structure Authority --- Frozen

Owner-confirmed H4/H1 structure is authoritative.

Major structure rules include: - A single wick is insufficient to define
a major pivot. - Active impulse continues until a meaningful correction
forms. - Corrections below approximately 38.2% are internal/minor. -
Major HH/HL and LL/LH structures require confirmation. - Mixed structure
can remain part of the prior trend/range until decisive break and
confirmation. - Reversal requires break/hold plus a confirmation
pivot. - Owner H4 confirmation/override remains part of the system.

Every confirmed structure must be preserved historically. A new
confirmation must never overwrite an older owner-confirmed impulse.

## 7. Structure Intelligence Registry --- Frozen Design

Atlas must maintain a shared authoritative structure history used by: -
Research Laboratory - Watchlist - Market Intelligence - Supervisor -
Trading - Future backtesting and research

Each historical structure record should preserve, where applicable: -
Symbol - Timeframe - Direction - Impulse start price/time - Impulse end
price/time - Correction depth - Trend/phase - Atlas-proposed
interpretation - Owner-confirmed interpretation - Confirmation time -
Later invalidation/break - Relationship to subsequent structure

When Atlas and the owner disagree, both interpretations must be
retained. Owner confirmation is ground truth.

## 8. Research Laboratory --- Frozen Product Definition

The Laboratory is an evidence/research environment, not a trading-chart
page.

Main page: - Existing universal Atlas status header - Research Lab
identity - Visible `RESEARCH ONLY — NO EXECUTION` - Full-width Research
Symbols / Research Watchlist - Research Patterns - Pattern × Symbol
Discovery - Research summary - Recommendations/findings

No large MT5/candlestick price chart belongs on the Laboratory page.

Approved drill-down routes: - `/research/symbol/{symbol}` -
`/research/pattern/{pattern}` - `/research/discovery/{symbol}/{pattern}`

Research detail pages focus on statistics, evidence, conditions and
conclusions.

Useful non-price visualizations are encouraged, especially: - 3D-style
columns - gauges / odometers - sample-health indicators - confidence
indicators - distribution charts

## 9. Research Symbol Workflow

The Research Watchlist requires `+ ADD SYMBOL`.

Adding a research symbol must: 1. Validate the exact instrument against
connected MT5. 2. Resolve broker symbol naming when needed. 3.
Subscribe/register market data. 4. Add the instrument to the research
universe only. 5. Record date/time added. 6. Begin collecting
observations from that point forward. 7. Run approved registered
research detectors. 8. Never enable execution merely because the symbol
was added.

Actions: - View Research - Pause Research - Remove from active research
without deleting historical evidence - Candidate for Trading

## 10. Structure Confirmation for New Symbols

Before structure-dependent research/trading proceeds on a newly added
symbol, Atlas must request owner confirmation of: - H4 trend - Last
valid H4 impulse start - Last valid H4 impulse end - Relevant timestamps
where available - Relevant H1 structure/state

When structure becomes genuinely invalid or a new major structure
requires confirmation: - State becomes `STRUCTURE REVIEW REQUIRED`. -
Structure-dependent trade approvals are blocked. - Raw observation
collection may continue. - Owner supplies a new confirmation. - Previous
confirmations remain immutable history.

## 11. Research Pattern Management

-   Existing registered detectors may be enabled/disabled for research
    through controlled UI/configuration.
-   A truly new pattern concept requires backend detector implementation
    and tests.
-   Arbitrary text must not dynamically invent trading logic.

## 12. Promotion to Trading --- Frozen

Controlled workflow:

`RESEARCH -> TRADING CANDIDATE -> OWNER APPROVAL -> APPROVED WATCHLIST`

Promotion must support symbol-specific permitted patterns.

A promoted symbol does not automatically receive permission to trade
every registered pattern.

No direct Laboratory-to-MT5-order shortcut is permitted.

## 13. Research Backend Architecture --- Frozen

One source of truth:

`MT5 Market Data` → `Research Data Collector` →
`Research Symbol Registry` → `Structure Intelligence Registry` →
`Pattern Detector Registry` → `Research Observation Store` →
`Research Statistics Engine` → `Research Read Model/API` →
`Laboratory UI`

Trading promotion remains separate:

`Validated Research Finding` → `Trading Candidate` → `Owner Approval` →
`Trading Watchlist Configuration` → `Supervisor` → `Risk` →
`Demo Execution`

## 14. Instrument Icon System --- Frozen

Existing icon identities: - EURUSD --- blue/cyan euro - USDJPY ---
purple/violet yen - USDCAD --- green dollar - XAUUSD --- gold/orange
gold bars

Approved conceptual extensions: - BTCUSD --- red/orange Bitcoin - USOIL
--- cyan/teal oil - XAGUSD --- cool blue/silver bars - GBPUSD ---
magenta/pink pound

The same instrument icon identity must persist across Research,
Watchlist and detail pages. Promotion to trading does not change the
icon.

## 15. Current Runtime Observations

Observed during today's VPS review: - A live 4-symbol refresh process
was repeatedly reporting `refreshed 4 symbols; entry_window=True`. - A
Shadow Supervisor process was repeatedly reporting four-symbol refreshes
with `execution=LOCKED; cost_policy=True`. - Earlier supervised demo
runtime output showed execution transport armed for DEMO while real
money remained forbidden. - Human H4 approval data was present for the
frozen symbols. - `runtime/dashboard_state.json` was observed updating
during runtime. - Secure staging web uses loopback `127.0.0.1:8080`. -
Several old diagnostic PowerShell/Command Prompt windows were identified
as safe to close when they had returned to a normal prompt and were not
hosting a running process. - An old diagnostic CMD that only searched
files/checked port 8080 and returned to `C:\Atlas>` was explicitly
identified as safe to close.

## 16. Important Web/Research Endpoint Observation

During today's checks, `/api/research` returned HTTP 404 from the
currently running secure-staging web instance in at least one test. This
is an unresolved implementation/runtime alignment item and must be
audited next session rather than worked around by rebuilding the frozen
architecture.

## 17. Existing Web Architecture Boundary

Frozen conceptual path:

`Frontend` → `/api/watchlist` → `run_secure_staging_web.py` →
`APP.watchlist(user)` → `AtlasReadModelService.watchlist()` →
`runtime/dashboard_state.json`

The web/read-model boundary must remain separate from MT5 order
execution.

## 18. End-of-Day Freeze

Do not perform additional structural changes after this checkpoint
today.

Next session should begin with: 1. Verify the exact four required
persistent runtime processes/windows and remove remaining
duplicate/diagnostic shells. 2. Verify the process owning port 8080 and
its exact command line/path. 3. Confirm the active secure-staging source
is the intended current Atlas source. 4. Audit why `/api/research` is
returning 404 despite Research route work appearing in source snippets.
5. Confirm the Laboratory backend/frontend against the frozen
specification. 6. Verify Structure Intelligence persistence and
owner-confirmation history. 7. Verify research-to-trading promotion
safety boundary. 8. Run integration/safety tests. 9. Continue the
end-to-end DEMO pipeline only after the above is clean.

## 19. Repository

Repository: `MShariati45/Atlas-Trading-Expert`\
Branch: `main`

Earlier frozen checkpoint: `docs/GITHUB_CHECKPOINT_2026-08-29.md`

This 2026-08-30 checkpoint supersedes it only for progress/status
additions. All previously frozen requirements remain binding unless
explicitly changed by the owner.
