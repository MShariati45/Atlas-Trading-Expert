ATLAS v0.24.16 - M15 Candlestick S/R Live Confluence

Purpose
- Integrates only the strongest v0.24.15 candlestick-at-support/resistance combinations.
- Candlestick specialist is enabled in the demo-candidate profile but execution remains hard locked.
- Candlestick specialist is independent of H4/H1 trend alignment.
- It only triggers at the researched D1/H4/H1 S/R timeframe for the specific symbol/pattern combination.
- If a candlestick trigger and another M15 specialist (for example a channel) agree on direction in the same area/bar, the Coordinator records independent multi-agent confluence and forwards it to the Supervisor.

Risk / execution
- Target for candlestick specialist: 2R.
- Existing Atlas risk policy remains unchanged.
- No live-money execution is enabled by this package.

Whitelisted setups
EURUSD
- Shooting Star/Pin at H4 resistance, counter-move required
- Evening Star at H4 resistance, counter-move required
- Bearish Engulfing at H4 resistance, counter-move not required

USDJPY
- Morning Star at H1 support, counter-move required
- Hammer/Pin at H1 support, counter-move not required
- Bullish Engulfing at H1 support, counter-move required
- Morning Star at H4 support, counter-move required

USDCAD
- Shooting Star/Pin at D1 resistance, counter-move required
- Morning Star at H4 support, counter-move required
- Evening Star at D1 resistance, counter-move required

XAUUSD
- Shooting Star/Pin at H4 resistance, counter-move not required
- Morning Star at H1 support, counter-move required
- Shooting Star/Pin at H1 resistance, counter-move required

Toggle
- The specialist is represented by CANDLESTICK_SR_REVERSAL in the demo profile.
- Set that pattern rule enabled=false for a symbol to disable it for that symbol.

Validation
- Full regression suite: 246/246 passed.
