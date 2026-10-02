# Atlas v2 P1 Owner Entry & Stop-Loss Freeze

Owner: Ali Shariati
Date: 2026-10-02
Status: FROZEN for P1 strategy implementation

Source supplied by owner:
`/Users/alishaariati/Desktop/Atlas_Entry_StopLoss_QA.pdf`

SHA-256:
`45a83b5c9f0dc6240143dfff1ca3e4a0c367c635e4ef2d8e77656cee32ec0e86`

The source is also archived in the Atlas Obsidian vault under:
`03_DECISIONS/Source Evidence/Atlas_Entry_StopLoss_QA_2026-10-02.pdf`

This decision closes the prior P0-level ambiguity that Atlas must not invent one universal entry rule. Entry and invalidation are pattern-specific and are defined from completed M15 structure. H4/Fibonacci is context/location only and never the trigger.
## Frozen entry rules

### M15 correction-reversal
- Long: completed M15 close above the last meaningful corrective lower high; entry at the next M15 open.
- Short: completed M15 close below the last meaningful corrective higher low; entry at the next M15 open.
- Stop: beyond the final correction swing extreme.

### Direct breakout
- Long: completed M15 close above structural resistance/range boundary; entry at the next M15 open.
- Short: completed M15 close below structural support; entry at the next M15 open.
- Stop: beyond the last meaningful pre-breakout/pre-breakdown swing extreme.

### Breakout + retest
- Require confirmed breakout, retest of the broken level, and a completed rejection candle.
- Long entry: above the bullish rejection candle high; stop below the retest swing low.
- Short entry: below the bearish rejection candle low; stop above the retest swing high.
### Bull Flag / Bear Flag
- Bull Flag: completed M15 close above the upper flag boundary; buy the next candle.
- Bear Flag: completed M15 close below the lower flag boundary; sell the next candle.
- Stop beyond the meaningful flag swing extreme.

### Horizontal range / consolidation
- Long: completed M15 close above range resistance; buy the next candle; stop below the last valid internal swing low that launched the breakout.
- Short: completed M15 close below range support; sell the next candle; stop above the last valid internal swing high.

## Structural and Fibonacci rules

- M15 pattern structure determines both trigger and invalidation.
- Structural levels may be corrective highs/lows, swing highs/lows, range boundary, flag boundary, or a broken support/resistance level under retest.
- Fibonacci levels do not trigger entries.
- Do not choose an arbitrary stop merely because it produces a preferred R:R.
## Stop buffer and 2R rule

- Stop belongs beyond the structural invalidation extreme.
- Prefer a small volatility buffer beyond that extreme.
- P1 research variants are M15 ATR(14) multipliers: 0, 0.10, and 0.20 ATR.
- 0.10 ATR is the starting research value, not a universal optimum.
- Final buffer is selected by backtest per instrument.
- Determine valid entry and structural stop first.
- If the planned 2R target is not realistically available, reject the trade.
- Never tighten the structural stop merely to manufacture 2R.

## Implementation boundary

This freeze authorizes deterministic P1 strategy contracts and research variants. It does not authorize order execution.
The first Track A versions remain Shadow/replay only with `execution = NONE`.
## Operational details still not invented

The source does not define these mechanics precisely enough to hard-code silently:

1. Exact price/fill convention for "buy/sell the next candle" in Flag and Horizontal Range shorthand.
2. Exact trigger offset/fill convention for "above/below" the breakout-retest rejection candle.
3. What makes a swing "meaningful" or "valid".
4. What qualifies as a retest that "held".
5. What qualifies as the bullish/bearish rejection candle.
6. Exact structural support/resistance identification rules where the source uses those terms.
7. The quantitative test for whether 2R is "realistically available".
8. The final ATR buffer for each instrument.

Until each is resolved by explicit owner rule or a clearly labeled research convention, any outcome dependent on it must remain versioned and, where applicable, `PROXY_OUTCOME`.

H1 remains context-only under the earlier frozen Atlas strategy record; it is informational and is not a universal hard gate.
