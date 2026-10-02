"""Small P0 replay coordinator for already-captured deterministic units."""
from __future__ import annotations

from atlas2.evaluate.context import create_context
from atlas2.evaluate.ledger import evaluate_c0
from atlas2.replay.digest import confirm_aggregate, replay_digest_for_store


def evaluate_capture_c0(
    store,
    *,
    capture_unit_id: str,
    label_pin_id: str | None = None,
    macro_view_class: str = "PIT",
    mode: str = "REPLAY",
    manifest_id: str | None = None,
):
    ctx = create_context(
        store,
        capture_unit_id=capture_unit_id,
        label_pin_id=label_pin_id,
        macro_view_class=macro_view_class,
        mode=mode,
    )
    arms = evaluate_c0(store, ctx_id=ctx.ctx_id)
    if manifest_id is not None:
        confirm_aggregate(store, manifest_id, "capture_units", capture_unit_id)
        confirm_aggregate(store, manifest_id, "evaluation_contexts", ctx.ctx_id)
    return ctx, arms, replay_digest_for_store(store, manifest_id)
