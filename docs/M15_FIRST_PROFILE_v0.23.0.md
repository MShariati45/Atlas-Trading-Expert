# Atlas v0.23.0 - M15-First Candidate Profile

## Purpose

This checkpoint converts the 2025-08-19 to 2026-08-19 broker-native research into a configurable **candidate** operating profile. It does not claim production readiness and does not enable live order execution.

## Hierarchy change

Old research hierarchy:

`H4/H1 full alignment -> Fibonacci >= 38.2% -> M15 discovery`

v0.23.0 candidate hierarchy:

`M15 discovery in both directions -> symbol/pattern-specific H4/H1 context -> Supervisor -> safety/risk gates`

Fibonacci remains measurable in the codebase but is **disabled as a permission gate and hidden by the candidate profile**.

## Watchlist

Only four symbols are enabled:

- EURUSD
- GBPUSD
- USDCAD
- XAUUSD

## Pattern switches

### EURUSD
Enabled: Channel Boundary Rejection (2R), Head & Shoulders, Impulse & Correction, Triangle/Wedge.
Disabled: original Channel Breakout, Flag/Pennant, Multiple Top/Bottom.
HTF context for enabled families: M15 direction aligned with H4 while H1 is opposed/corrective.

### GBPUSD
Enabled: Channel Boundary Rejection (3R), Impulse & Correction (2R).
Disabled: original Channel Breakout, Flag/Pennant, Head & Shoulders, Multiple Top/Bottom, Triangle/Wedge.
HTF context: H4 aligned / H1 opposed for the two enabled candidates.

### USDCAD
Enabled: Channel Boundary Rejection (3R), Head & Shoulders, Impulse & Correction, Multiple Top/Bottom, Triangle/Wedge.
Disabled: original Channel Breakout and Flag/Pennant.
Boundary Channel: both H4 and H1 opposed to the M15 trade. Other enabled patterns: H4 aligned / H1 opposed.

### XAUUSD
Enabled: Channel Boundary Rejection (3R), Flag/Pennant, Head & Shoulders, Impulse & Correction, Multiple Top/Bottom, Triangle/Wedge.
Disabled: original Channel Breakout.
Boundary Channel: both H4 and H1 opposed. Other enabled patterns: H4 aligned; H1 is advisory only because the holdout sample provided little independent H1 contrast.

## Risk and trading limits

- Daily risk cap: **1.0%**
- Risk per trade: **0.5%**
- Maximum new trades per day: **2**
- Maximum trades per symbol per day: **1**
- After two trades or 1.0% committed risk, new-entry search is disabled until the ledger resets for the next trading day.
- Once a symbol has traded, that symbol's entry search is disabled until the next trading day.
- New entries: Sunday market open through Thursday in `America/Vancouver`.
- Friday: no new entries; existing positions are managed/closed before the configured Friday flat window.

A literal Saturday-afternoon forex entry window is not configured because the spot-FX market is normally closed then; the candidate profile resumes at the Sunday broker market-open window.

## Capacity arithmetic

At most 2 trades/day across 5 entry sessions/week gives a hard ceiling of **10 trades/week**. Across 52 weeks this is **520 trades/year**, averaging about **43.3 trades/month** before holidays and inactive days. Therefore a goal of at least 40 executed trades/month is very close to the system's theoretical maximum capacity. Atlas should separately track **qualified opportunities found** and **trades actually executed** so frequency goals do not force low-quality entries.

## Multi-account architecture

The shared signal / isolated account architecture is retained. `MultiAccountExecutionPlanner` now builds independent account risk plans from one approved signal. It does not send orders. Each enabled account keeps its own equity and risk percentage.

## Safety status

Live execution remains disabled in this checkpoint. The new `run_m15_first_observer.py` is read-only and intended for paper/demo observation while the revised pattern set and hierarchy are revalidated.
