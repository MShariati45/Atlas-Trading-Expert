# Atlas v0.23.1 - M15-First Candidate Profile

## Purpose

This checkpoint updates the M15-first candidate watchlist after the 2025-08-19 to 2026-08-19 USDJPY study. GBPUSD is removed and USDJPY is added. Live order transmission remains disabled pending the next demo/run validation.

## Active watchlist

- EURUSD
- USDJPY
- USDCAD
- XAUUSD

## Hierarchy

`M15 mature pattern -> symbol/pattern-specific H4/H1 context -> Supervisor -> safety/risk gates`

Universal H1 alignment remains disabled. Fibonacci stays in the codebase but is disabled as an entry permission gate and hidden in this candidate profile.

## Pattern switches

### EURUSD
Enabled: Channel Boundary Rejection 2R, Head & Shoulders 2R, Impulse & Correction 2R, Triangle/Wedge 2R.
HTF: H4 aligned / H1 opposed. Flag/Pennant, Multiple Top/Bottom and original Channel Breakout are disabled.

### USDJPY
Enabled: Channel Boundary Rejection 2R, Flag/Pennant 2R, Head & Shoulders 2R, Triangle/Wedge 2R.
- Channel Boundary Rejection: no hard H4/H1 gate in this candidate.
- Flag/Pennant: H4 + H1 aligned.
- Head & Shoulders: H4 + H1 opposed to the M15 trade, treating it as reversal context.
- Triangle/Wedge: H4 + H1 aligned.
Impulse & Correction, Multiple Top/Bottom and original Channel Breakout are disabled.

### USDCAD
Enabled: Channel Boundary Rejection 3R, Head & Shoulders, Impulse & Correction, Multiple Top/Bottom, Triangle/Wedge.
Channel Boundary Rejection requires both H4/H1 opposed; other enabled families use H4 aligned / H1 opposed. Flag/Pennant and original Channel Breakout are disabled.

### XAUUSD
Enabled: Channel Boundary Rejection 3R plus Flag/Pennant, Head & Shoulders, Impulse & Correction, Multiple Top/Bottom and Triangle/Wedge at 2R.
Channel Boundary Rejection uses both H4/H1 opposed. Other enabled patterns require H4 alignment while H1 remains advisory. Original Channel Breakout is disabled.

## Risk and trading limits

- 0.50% risk per trade
- 1.00% maximum new risk per trading day
- maximum two new trades per day
- maximum one trade per symbol per day
- after the second trade or 1.00% committed risk, entry scanning is disabled until the next trading day
- Sunday market open through Thursday in America/Vancouver
- no Friday new entries; force-flat behavior remains configured before the Friday close window

## Multi-account support

The shared-signal / isolated-account planning architecture remains enabled. Each connected MT5 account can receive an independent risk plan from the same approved Atlas signal. Execution transport remains disabled until explicit live approval.

## Research rationale

USDJPY materially outperformed GBPUSD in the current one-year candidate study. The provisional four-symbol portfolio EURUSD + USDJPY + USDCAD + XAUUSD produced materially better trade frequency and portfolio expectancy than the GBPUSD version, but the same period was used to select the USDJPY rules. Therefore v0.23.1 remains a candidate configuration and requires unseen/demo validation before live prop deployment.
