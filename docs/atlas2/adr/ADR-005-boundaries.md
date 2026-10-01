# ADR-005 — Package and Execution Boundaries

Owner: Ali Shariati
Status: Accepted

`atlas2` is a sibling package and P0 artifact with no `atlas.*`, broker SDK, execution, dispatch, or transport imports.
Legacy execution remains untouched until P2.
For P2, prefer an adapter/bridge; any unavoidable legacy change must be a separately versioned, owner-approved fork.
Live enable later requires both DB approval and a matching host-local enable token.
