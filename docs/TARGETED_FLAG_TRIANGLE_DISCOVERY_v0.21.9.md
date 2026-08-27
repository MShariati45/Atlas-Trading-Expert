# Atlas Trading Expert v0.21.9 - Targeted Flag / Triangle Discovery Validation

## Scope
This checkpoint starts from v0.21.8 and changes only M15 live candidate discovery. H4, H1, Fibonacci, specialist pattern rules, Coordinator logic, Supervisor rules, and risk policy are unchanged.

## Defect 1 - Flag breakout candle contaminated consolidation geometry
The live runtime previously built the four-bar flag consolidation including the same completed M15 candle that was immediately tested for breakout. Because a candle close cannot close above its own high or below its own low, ordinary shallow-phase flag breakouts were effectively suppressed.

### Fix
Flag/pennant discovery now freezes its pole and consolidation from bars preceding the current completed M15 candle. The current candle is then passed to the specialist as the potential breakout candle.

## Defect 2 - Triangle first structural S/R was not actually the first external obstacle
Candidate discovery previously selected an extreme historical swing and could overlap swings already belonging to the current formation. It could also synthesize an ATR-based fallback level when no validated external swing existed.

### Fix
The runtime now:
- excludes the current formation reaction swings when searching for structural S/R;
- chooses the nearest validated external swing beyond the pattern boundary in the permitted direction;
- does not invent ATR-based support/resistance if no such validated external structure exists.

## Targeted diagnostics - EURUSD 2021-05-01 to 2021-06-15
Before the discovery fix, Flag/Pennant and Triangle/Wedge produced no actionable real-history events in v0.21.8.

After fixing discovery sequencing and structural S/R selection:
- 950 M15 bars were eligible under real H4/H1/Fibonacci gating.
- Flag candidate pipeline: 68 strong flagpoles validated, 54 consolidations matured, 21 consolidations were rejected as too deep, and 123 pole candidates were rejected as too weak.
- 13 unique Flag/Pennant VALID_TRIGGER events appeared naturally.
- 25 unique Triangle/Wedge VALID_TRIGGER events appeared using the currently implemented symmetrical-triangle discovery path.
- Existing H&S, Multiple Top/Bottom, Impulse/Correction, and Channel behavior remained present.
- 1 duplicate, 0 conflicts, and 4 independent confirmations were observed.
- Full regression suite: 162/162 passing.

## Cross-window confirmation
EURUSD 2020-09-01 to 2020-10-16:
- 1,028 eligible M15 bars.
- 3 Flag/Pennant VALID_TRIGGER events.
- 14 Triangle/Wedge VALID_TRIGGER events.
- Existing Channel/H&S triggers remained.

GBPUSD 2021-05-01 to 2021-06-15:
- 125 eligible M15 bars.
- 2 Triangle/Wedge VALID_TRIGGER events.
- 1 Multiple Top/Bottom EARLY_REVERSAL_CANDIDATE.

## Important remaining discovery gaps
The specialist engines support broader named pattern families, but the current live discovery layer does not yet fully discover all of them:
- Flag/Pennant live discovery currently proposes shape=FLAG; it does not independently classify PENNANT geometry.
- Triangle/Wedge live discovery currently proposes SYMMETRICAL_TRIANGLE from converging reaction envelopes; it does not yet independently classify ASCENDING_TRIANGLE, DESCENDING_TRIANGLE, RISING_WEDGE, or FALLING_WEDGE.

Therefore v0.21.9 is not a freeze of the entire Flag/Pennant or Triangle/Wedge family. It is a checkpoint proving the corrected real-history discovery path for flags and symmetrical triangles without loosening the specialist rules.

## Next step
Implement and validate pattern-specific candidate geometry for pennants, ascending/descending triangles, and rising/falling wedges as isolated discovery work. Each family must receive its own real-history evidence and rejection diagnostics before the M15 specialist layer can be fully frozen.
