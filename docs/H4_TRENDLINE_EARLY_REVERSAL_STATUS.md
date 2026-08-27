# Atlas v0.20 - H4 Trendline Early Reversal + Supervisor Integration

## Frozen behavior implemented
- H4 formal strategic trend remains separate from diagonal/trendline evidence.
- Bearish H4 structure builds descending trendlines from validated H4 swing highs.
- Bullish H4 structure builds ascending trendlines from validated H4 swing lows.
- Minimum 2 validated pivot touches; 3+ touches are marked STRONG quality.
- A trendline break alone is insufficient.
- First completed H4 close beyond the line => BREAKOUT_PENDING.
- A later completed H4 confirmation candle beyond the line in the breakout direction => EARLY_DIRECTION_CONFIRMED.
- Confirmed bearish-line break yields effective BULLISH search direction while formal H4 may remain BEARISH.
- Confirmed bullish-line break yields effective BEARISH search direction while formal H4 may remain BULLISH.
- H1 baseline does not run its own trendline subsystem; it receives H4 effective direction and must independently realign structurally.
- Supervisor may approve the early H4 path only when H1 matches the effective H4 direction and all Fibonacci, M15, static-zone, news, spread, stop, R:R, symbol-lock, daily-risk, day/session, and freshness gates pass.
- Early trendline direction cannot override a failed hard gate.

## Runtime additions
H4 state now exposes:
- trend (formal strategic trend)
- effective_direction
- trendline.status
- trendline.direction
- trendline.touch_count
- trendline.quality
- trendline.breakout_time / breakout_close
- trendline.confirmation_time
- trendline.early_direction

The live MT5 bootstrap seeds an initial diagonal line from recent validated H4 pivots when suitable. Incremental H4 bars maintain a small confirmed-pivot buffer and can refresh the line without rescanning full history.

## Diagnostic validator
The H4 validator now emits `trendline_analysis` alongside strategic origin/endpoint/control-pivot output so a historical EURUSD validation can show whether a current formal bearish/bullish regime also carries an earlier confirmed opposite directional signal.

## Safety
This build remains read-only/paper architecture. No live execution permission is enabled by the trendline component.
