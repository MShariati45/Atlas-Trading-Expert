# M15 Multiple Top / Multiple Bottom Engine - v0.5

Implemented live-scope pattern family:
- Double Top
- Double Bottom
- Triple Top
- Triple Bottom

Rules encoded:
- Pattern family is reversal-context specific: top after bullish prior trend, bottom after bearish prior trend.
- Tops/bottoms may differ slightly; tolerance is configurable as a fraction of M15 ATR.
- Second/third extreme alone is never an entry trigger.
- Pattern becomes mature only after the required reaction pivots exist.
- A closed M15 bar through the neckline creates EARLY_REVERSAL_CANDIDATE.
- Neckline confirmation notifies the M15 Impulse & Correction agent to re-evaluate independently.
- Pattern confirmation does not force CHoCH/BOS or overwrite the structure agent.
- Pattern stop proposal uses the pattern extreme plus a configurable spread/ATR/wick/tick buffer.
- Early candidates become stale after a configurable number of bars.
- Busted patterns are invalidated if price subsequently violates the defining top/bottom extreme.

Research modes retained for later comparison:
1. Early neckline-confirmed entry.
2. Later independently structure-confirmed entry.
