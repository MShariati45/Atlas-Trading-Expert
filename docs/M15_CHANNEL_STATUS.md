# M15 Channel Agent - v0.9

- Activates at H1 Fibonacci retracement >= 38.2%.
- LONG context expects a descending corrective channel; SHORT context expects an ascending corrective channel.
- Requires meaningful reaction highs/lows and reasonably parallel boundaries.
- Does not trade internal channel oscillations.
- Requires a full M15 close outside the corrective boundary.
- Boundary break alone is not a trigger: continuation outside the channel or a successful retest/rejection is required.
- No Triangle/Wedge first-support/resistance-break rule is imported.
- Failed break/re-entry invalidates the setup.
- Structural stop uses the preferred retest pivot when available, otherwise the stored channel structural anchor, plus the shared symbol-aware spread/ATR/wick/tick buffer.
