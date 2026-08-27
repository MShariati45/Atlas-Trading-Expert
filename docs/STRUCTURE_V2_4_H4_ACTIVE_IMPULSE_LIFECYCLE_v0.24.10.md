# Atlas Structure V2.4 - H4 Active Impulse Lifecycle (v0.24.10)

Research-only refinement. Production/shadow execution is unchanged and remains locked.

## Core distinction
The H4 agent now separates broad dominant strategic structure from the active/current strategic impulse. A historical strategic pivot may remain in structural history without being the origin of the current impulse.

## Lifecycle corrections
1. **Origin breach resets the stale cycle.** `IMPULSE_ORIGIN_BREACHED` no longer freezes the old origin indefinitely. The breach extreme re-seeds the timeframe-local cycle, after which normal H4 structure must rebuild.
2. **Fast H4 corrections can qualify.** A material countertrend swing may be admitted even when a wide macro pivot wing misses it, provided both sides of the reaction are sufficiently large in H4 ATR terms.
3. **Retrospective scale normalization.** A correction that looked deep while an impulse was short can later become minor after the directional leg extends. Promoted corrections are therefore re-evaluated against the eventual/current H4 leg and demoted if they become <38.2%. This is a current-structure interpretation; historical real-time classifications remain auditable separately.
4. **Pivot-zone lifecycle.** Distant touches at similar prices are split into separate episodes. H4 requires a separated multi-reaction zone, and a zone formed after the last strategic extreme cannot replace the active origin until price makes a fresh strategic HH/LL.
5. **Wick handling remains intact.** Isolated wick-dominated spikes are excluded from strategic zone construction.

## Teaching cases
The runner scores four manual teaching labels only after detection. No symbol-specific target prices are used by `analyze_structure`.

- XAUUSD: ~4310.66 -> ~4630, bullish impulse.
- EURUSD: ~1.15124 -> ~1.17108, bullish.
- USDJPY: ~160.388 -> ~155.235, bearish; current correction/range.
- USDCAD: ~1.41273 -> ~1.37312, bearish impulse.

## Safety
This branch is read-only research. It does not alter the running shadow supervisor, execution gates, risk rules, news logic, entries, stops, targets, or production H4/H1/M15 agents.
