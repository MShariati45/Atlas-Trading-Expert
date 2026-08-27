# H4 Human Approval Gate v0.24.17

Purpose: make the owner's H4 view authoritative for demo execution while Atlas continues to make and log its own prediction.

- Local JSON state only; zero LLM/API calls.
- Per symbol: BULLISH, BEARISH, RANGE, TRANSITION plus optional/required impulse bounds.
- BULLISH/BEARISH require start and end. RANGE/TRANSITION deliberately block directional entries.
- Missing approval blocks that symbol only.
- A trade direction that conflicts with the human-approved H4 direction is blocked.
- Atlas's prediction is preserved separately so disagreements can later become training data.
- This version does not unlock MT5 order execution.

Examples:
`set_h4_approval.bat XAUUSD BULLISH --start 4310.66 --end 4629.13`
`set_h4_approval.bat EURUSD RANGE`
`set_h4_approval.bat USDCAD --revoke`

State file: `runtime/h4_human_approvals.json`.
