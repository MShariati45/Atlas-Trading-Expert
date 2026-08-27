# Atlas H1 Independent Structure Agent - v0.21.1

## Frozen architectural boundary
H1 reads H1 data only. It does not receive or store H4 trend, H4 effective direction,
H4 pivots, H4 impulses, H4 trendline state, alignment state, Fibonacci permission, or
M15 permission.

H4 and H1 publish independent reports. `HTFAlignmentService` compares the completed
reports downstream and never writes the result back into either structure agent.

## H1 report owns only
- H1 strategic trend
- H1 phase
- H1 strategic origin
- H1 strategic endpoint/current extreme
- H1 control/protected pivot
- H1 correction extreme/depth/qualification
- H1 continuation/reversal-candidate state
- H1 audit/reason codes

## Hard guard
If an H1 bar event contains an H4-prefixed field, H1 returns
`H1_CROSS_TIMEFRAME_INPUT_FORBIDDEN` and does not update its state.

## Downstream flow
H4 report + H1 report -> HTFAlignmentService -> Fibonacci eligibility -> M15 pipeline.
