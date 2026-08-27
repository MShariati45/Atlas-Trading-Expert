from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable

FIB_CANDIDATE_MIN = 0.382
FIB_HARD_INVALIDATION = 1.0
MIN_CORRECTION_BARS = 3
MIN_COUNTER_BODY_BARS = 2
MIN_BODY_DISPLACEMENT_ATR = 0.80
STRATEGIC_ZONE_ATR_TOLERANCE = 0.35
CYCLE_LOOKBACK = {"H4": 420, "H1": 320, "M15": 480, "M5": 640}


@dataclass(slots=True)
class ResearchPivot:
    index: int
    time: str
    price: float
    kind: str
    major: bool = False
    reason: str = "LOCAL_SWING"


@dataclass(slots=True)
class CorrectionQuality:
    start_index: int
    end_index: int
    depth: float
    close_depth: float
    bars: int
    counter_body_bars: int
    body_displacement_atr: float
    wick_dominated: bool
    structural_acceptance: bool
    qualified: bool
    reason: str


@dataclass(slots=True)
class CorrectionAudit:
    trend: str
    origin_index: int
    endpoint_index: int
    pivot_index: int
    pivot_time: str
    pivot_price: float
    quality: CorrectionQuality
    promoted: bool


@dataclass(slots=True)
class StructureResearchResult:
    symbol: str
    timeframe: str
    dominant_trend: str
    regime: str
    transition_state: str
    impulse_origin: ResearchPivot | None
    impulse_endpoint: ResearchPivot | None
    control_pivot: ResearchPivot | None
    strategic_pivots: list[ResearchPivot]
    internal_pivots: list[ResearchPivot]
    current_correction: CorrectionQuality | None
    trendline_anchor_count: int
    correction_audit: list[CorrectionAudit]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bar_dict(bar: Any) -> dict[str, Any]:
    if isinstance(bar, dict):
        return bar
    t = getattr(bar, "time_utc", getattr(bar, "time", None))
    return {
        "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
    }


def _bars(raw: Iterable[Any]) -> list[dict[str, Any]]:
    out = [_bar_dict(x) for x in raw]
    for b in out:
        for k in ("open", "high", "low", "close"):
            b[k] = float(b[k])
        b["time"] = str(b["time"])
    return out


def _atr(bars: list[dict[str, Any]], period: int = 14) -> list[float]:
    if not bars:
        return []
    trs: list[float] = []
    prev = bars[0]["close"]
    for b in bars:
        tr = max(b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev))
        trs.append(tr)
        prev = b["close"]
    out: list[float] = []
    for i in range(len(trs)):
        lo = max(0, i - period + 1)
        chunk = trs[lo : i + 1]
        out.append(sum(chunk) / max(1, len(chunk)))
    return out


def _local_pivots(bars: list[dict[str, Any]], wing: int) -> list[ResearchPivot]:
    pivots: list[ResearchPivot] = []
    for i in range(wing, len(bars) - wing):
        c = bars[i]
        left = bars[i-wing:i]
        right = bars[i+1:i+1+wing]
        if c["high"] > max(x["high"] for x in left) and c["high"] >= max(x["high"] for x in right):
            pivots.append(ResearchPivot(i, c["time"], c["high"], "HIGH"))
        if c["low"] < min(x["low"] for x in left) and c["low"] <= min(x["low"] for x in right):
            pivots.append(ResearchPivot(i, c["time"], c["low"], "LOW"))
    pivots.sort(key=lambda p: (p.index, 0 if p.kind == "LOW" else 1))
    return pivots




def _pivot_is_wick_dominated(bars: list[dict[str, Any]], p: ResearchPivot) -> bool:
    b = bars[p.index]
    rng = max(b["high"] - b["low"], 1e-12)
    body = abs(b["close"] - b["open"])
    if p.kind == "LOW":
        tail = min(b["open"], b["close"]) - b["low"]
    else:
        tail = b["high"] - max(b["open"], b["close"])
    return tail / rng >= 0.60 and body / rng <= 0.35


def _current_cycle_zone_origin(
    bars: list[dict[str, Any]],
    atr: list[float],
    raw_pivots: list[ResearchPivot],
    trend: str,
    *,
    cycle_start: int,
    min_reaction_gap: int = 3,
    max_episode_gap: int | None = None,
) -> ResearchPivot | None:
    """Find a current strategic pivot zone from repeated meaningful timeframe-local touches.

    Two separated touches confirm a zone. The second touch becomes the structural anchor;
    later touches inside the same ATR-normalized zone are retests and do not reset origin.
    Isolated wick spikes are excluded from zone construction.
    """
    kind = "LOW" if trend == "BULLISH" else "HIGH"
    pts = [p for p in raw_pivots if p.kind == kind and p.index >= cycle_start and not _pivot_is_wick_dominated(bars, p)]
    if len(pts) < 2:
        return None
    zones: list[dict[str, Any]] = []
    for p in pts:
        tol = 0.45 * max(atr[p.index] if atr else 0.0, 1e-12)
        best = None
        best_dist = None
        for z in zones:
            dist = abs(p.price - z["center"])
            episode_ok = max_episode_gap is None or p.index - z["touches"][-1].index <= max_episode_gap
            if episode_ok and dist <= max(tol, z["tol"]):
                if best_dist is None or dist < best_dist:
                    best, best_dist = z, dist
        if best is None:
            zones.append({"center": p.price, "tol": tol, "touches": [p]})
        else:
            best["touches"].append(p)
            # Robust center: mean of non-wick structural touches.
            best["center"] = sum(x.price for x in best["touches"]) / len(best["touches"])
            best["tol"] = max(best["tol"], tol)

    qualified = []
    for z in zones:
        touches = z["touches"]
        # Require two distinct structural reactions, not neighboring candles of one wick event.
        confirm = None
        first = touches[0]
        opposite = "HIGH" if kind == "LOW" else "LOW"
        for t in touches[1:]:
            # A second touch must be a separate structural reaction, with an
            # intervening opposite swing. Multiple lows/highs inside one pullback
            # are one episode, not multiple confirmations.
            separated_reaction = any(first.index < q.index < t.index and q.kind == opposite for q in raw_pivots)
            if t.index - first.index >= min_reaction_gap and separated_reaction:
                confirm = t
                break
        if confirm is None:
            continue
        # Must have meaningful continuation after confirmation.
        future = bars[confirm.index + 1:]
        if not future:
            continue
        atr_here = max(atr[confirm.index], 1e-12)
        if trend == "BULLISH":
            displacement = max(b["high"] for b in future) - confirm.price
        else:
            displacement = confirm.price - min(b["low"] for b in future)
        if displacement < 1.5 * atr_here:
            continue
        qualified.append((len(touches), confirm.index, displacement / atr_here, confirm, z))

    if not qualified:
        return None
    # Latest confirmed structural zone wins. Later touches in that same zone are retests.
    _, _, _, confirm, _ = max(qualified, key=lambda x: (x[0], x[1]))
    confirm.major = True
    confirm.reason = "CURRENT_CYCLE_PIVOT_ZONE_CONFIRMED"
    return confirm

def _compress_alternating(pivots: list[ResearchPivot]) -> list[ResearchPivot]:
    out: list[ResearchPivot] = []
    for p in pivots:
        if not out or out[-1].kind != p.kind:
            out.append(p)
            continue
        prev = out[-1]
        more_extreme = p.price > prev.price if p.kind == "HIGH" else p.price < prev.price
        if more_extreme:
            out[-1] = p
    return out


def _correction_quality(
    bars: list[dict[str, Any]],
    atr: list[float],
    *,
    impulse_origin: ResearchPivot,
    impulse_endpoint: ResearchPivot,
    correction_pivot: ResearchPivot,
    trend: str,
) -> CorrectionQuality:
    size = abs(impulse_endpoint.price - impulse_origin.price)
    depth = abs(correction_pivot.price - impulse_endpoint.price) / max(size, 1e-12)
    start = impulse_endpoint.index + 1
    end = correction_pivot.index
    if end < start:
        start = end
    segment = bars[start:end+1] if end >= start else [bars[correction_pivot.index]]

    counter = 0
    body_move = 0.0
    max_wick_fraction = 0.0
    if trend == "BULLISH":
        accepted_extreme = min(min(b["open"], b["close"]) for b in segment)
        close_depth = max(0.0, impulse_endpoint.price - accepted_extreme) / max(size, 1e-12)
    else:
        accepted_extreme = max(max(b["open"], b["close"]) for b in segment)
        close_depth = max(0.0, accepted_extreme - impulse_endpoint.price) / max(size, 1e-12)

    for b in segment:
        body = abs(b["close"] - b["open"])
        rng = max(b["high"] - b["low"], 1e-12)
        if trend == "BULLISH" and b["close"] < b["open"]:
            counter += 1
            body_move += body
        elif trend == "BEARISH" and b["close"] > b["open"]:
            counter += 1
            body_move += body
        max_wick_fraction = max(max_wick_fraction, 1.0 - body / rng)

    atr_slice = atr[start:end+1] if atr and end >= start else []
    avg_atr = sum(atr_slice) / max(1, len(atr_slice)) if atr_slice else 0.0
    body_atr = body_move / max(avg_atr, 1e-12)
    bars_n = max(1, end - start + 1)

    depth_ok = depth > FIB_CANDIDATE_MIN
    structural_acceptance = close_depth >= FIB_CANDIDATE_MIN
    development_ok = (
        bars_n >= MIN_CORRECTION_BARS
        and counter >= MIN_COUNTER_BODY_BARS
        and body_atr >= MIN_BODY_DISPLACEMENT_ATR
    )
    wick_dominated = depth_ok and not structural_acceptance and max_wick_fraction >= 0.55
    qualified = (
        depth_ok
        and structural_acceptance
        and development_ok
        and not wick_dominated
        and depth < FIB_HARD_INVALIDATION
    )

    if depth >= FIB_HARD_INVALIDATION:
        reason = "IMPULSE_ORIGIN_BREACHED"
    elif not depth_ok:
        reason = "DEPTH_NOT_BEYOND_38_2"
    elif not structural_acceptance:
        reason = "WICK_ONLY_OR_NO_BODY_ACCEPTANCE_BEYOND_38_2"
    elif not development_ok:
        reason = "INSUFFICIENT_MULTI_CANDLE_DEVELOPMENT"
    else:
        reason = "QUALIFIED_STRUCTURAL_CORRECTION"
    return CorrectionQuality(
        start, end, depth, close_depth, bars_n, counter, body_atr,
        wick_dominated, structural_acceptance, qualified, reason,
    )


def _trendline_supports(anchors: list[ResearchPivot], atr_now: float, trend: str) -> bool:
    if len(anchors) < 2:
        return False
    a, b = anchors[-2], anchors[-1]
    if b.index <= a.index:
        return False
    if trend == "BULLISH" and not (b.price > a.price):
        return False
    if trend == "BEARISH" and not (b.price < a.price):
        return False
    return isfinite(atr_now) and atr_now >= 0.0


def _broad_direction(bars: list[dict[str, Any]]) -> str:
    # Broad timeframe-local direction only; no higher-timeframe inheritance.
    lookback = min(160, len(bars) - 1)
    start = bars[-1-lookback]["close"]
    end = bars[-1]["close"]
    if end > start:
        return "BULLISH"
    if end < start:
        return "BEARISH"
    return "UNRESOLVED"


def _build_persistent_chain(
    bars: list[dict[str, Any]],
    atr: list[float],
    pivots: list[ResearchPivot],
    trend: str,
    *,
    cycle_start: int = 0,
    promotion_indices: set[int] | None = None,
    require_continuation_confirmation: bool = False,
) -> tuple[list[ResearchPivot], list[CorrectionAudit]]:
    """Build a strategic chain while preserving timeframe hierarchy.

    v0.24.9 adds two H4-specific safeguards when requested by the caller:
    1) only timeframe-scale (macro) correction pivots may become strategic HL/LH;
    2) a qualified correction is only promoted after price subsequently makes a new
       directional extreme beyond the prior endpoint. Until then, the previous
       completed impulse remains the last strategic impulse and the market is in
       correction/range.
    """
    origin_kind = "LOW" if trend == "BULLISH" else "HIGH"
    endpoint_kind = "HIGH" if trend == "BULLISH" else "LOW"
    candidates = [p for p in pivots if p.kind == origin_kind and p.index >= cycle_start]
    if promotion_indices is not None:
        scaled = [p for p in candidates if p.index in promotion_indices]
        if scaled:
            candidates = scaled
    if not candidates:
        return [], []

    active_origin = candidates[0]
    active_origin.major = True
    active_origin.reason = "STRATEGIC_CHAIN_SEED"
    strategic = [active_origin]
    audits: list[CorrectionAudit] = []
    active_endpoint: ResearchPivot | None = None
    pending: tuple[ResearchPivot, CorrectionAudit, float] | None = None

    def endpoint_breaks(candidate: ResearchPivot, prior_price: float) -> bool:
        return candidate.price > prior_price if trend == "BULLISH" else candidate.price < prior_price

    def correction_more_extreme(a: ResearchPivot, b: ResearchPivot) -> bool:
        # Among multiple pivots inside one unfinished correction, keep the deepest
        # structurally valid correction pivot.
        return a.price < b.price if trend == "BULLISH" else a.price > b.price

    for p in pivots:
        if p.index <= active_origin.index:
            continue

        if p.kind == endpoint_kind:
            if pending is not None and active_endpoint is not None:
                pending_pivot, pending_audit, prior_endpoint_price = pending
                if p.index > pending_pivot.index and endpoint_breaks(p, prior_endpoint_price):
                    pending_pivot.major = True
                    pending_pivot.reason = "STRATEGIC_CORRECTION_CONFIRMED_BY_CONTINUATION"
                    pending_audit.promoted = True
                    strategic.append(pending_pivot)
                    active_origin = pending_pivot
                    active_endpoint = p
                    pending = None
                    continue
            if trend == "BULLISH":
                if active_endpoint is None or p.price > active_endpoint.price:
                    active_endpoint = p
            else:
                if active_endpoint is None or p.price < active_endpoint.price:
                    active_endpoint = p
            continue

        if p.kind != origin_kind or active_endpoint is None or p.index <= active_endpoint.index:
            continue

        q = _correction_quality(
            bars, atr,
            impulse_origin=active_origin,
            impulse_endpoint=active_endpoint,
            correction_pivot=p,
            trend=trend,
        )
        direction_ok = p.price > active_origin.price if trend == "BULLISH" else p.price < active_origin.price
        atr_here = atr[p.index] if atr else 0.0
        same_zone = abs(p.price - active_origin.price) <= STRATEGIC_ZONE_ATR_TOLERANCE * max(atr_here, 1e-12)
        scale_ok = promotion_indices is None or p.index in promotion_indices

        if same_zone and q.qualified:
            q.qualified = False
            q.reason = "RETEST_OF_ACTIVE_STRATEGIC_PIVOT_ZONE"
        elif q.qualified and not scale_ok:
            q.qualified = False
            q.reason = "LOWER_SCALE_CORRECTION_NOT_TIMEFRAME_STRATEGIC"

        audit = CorrectionAudit(
            trend, active_origin.index, active_endpoint.index, p.index, p.time, p.price, q, False
        )
        audits.append(audit)

        # v0.24.10: an origin breach ends the old impulse cycle.  The old
        # implementation merely rejected the pivot and kept evaluating every
        # future correction against a stale origin, which could lock H4 onto an
        # obsolete July/March structure.  Re-bootstrap from the breach extreme
        # and let subsequent continuation/corrections build the current cycle.
        if q.reason == "IMPULSE_ORIGIN_BREACHED":
            p.major = True
            p.reason = "CURRENT_CYCLE_RESEEDED_AFTER_ORIGIN_BREACH"
            active_origin = p
            active_endpoint = None
            pending = None
            strategic = [p]
            continue

        eligible = bool(q.qualified and direction_ok and not same_zone and scale_ok)
        if not eligible:
            continue

        if not require_continuation_confirmation:
            p.major = True
            p.reason = "QUALIFIED_STRATEGIC_CORRECTION_FROM_ACTIVE_IMPULSE"
            audit.promoted = True
            strategic.append(p)
            active_origin = p
            active_endpoint = None
            pending = None
            continue

        prior_endpoint_price = active_endpoint.price
        if pending is None or correction_more_extreme(p, pending[0]):
            if pending is not None:
                old_pivot, old_audit, _ = pending
                old_audit.quality.reason = "SUPERSEDED_BY_DEEPER_UNFINISHED_CORRECTION"
            q.reason = "QUALIFIED_CORRECTION_AWAITING_CONTINUATION"
            pending = (p, audit, prior_endpoint_price)

    return strategic, audits


def _h4_macro_promotion_indices(
    bars: list[dict[str, Any]],
    atr: list[float],
    raw_pivots: list[ResearchPivot],
    trend: str,
    *,
    cycle_start: int,
) -> set[int]:
    """Return H4-scale pivot indices eligible to become strategic HL/LH.

    H4 must not promote an H1-sized swing merely because it retraces 38.2% locally.
    We use a wider H4 pivot wing plus repeated structural-zone confirmation. This
    stays timeframe-local: it never reads H1 output.
    """
    macro = _compress_alternating(_local_pivots(bars, wing=6))
    wanted_kind = "LOW" if trend == "BULLISH" else "HIGH"
    idx = {
        p.index for p in macro
        if p.index >= cycle_start and p.kind == wanted_kind and not _pivot_is_wick_dominated(bars, p)
    }
    zone = _current_cycle_zone_origin(
        bars, atr, raw_pivots, trend, cycle_start=cycle_start,
        min_reaction_gap=6, max_episode_gap=48,
    )
    if zone is not None:
        idx.add(zone.index)
    # Permit a local pivot within one bar of a macro pivot. Broker/session alignment
    # can shift the exact H4 swing candle without changing the structural event.
    expanded = set(idx)
    for p in raw_pivots:
        if p.kind == wanted_kind and any(abs(p.index - i) <= 1 for i in idx):
            expanded.add(p.index)

    # Also admit a timeframe-local countertrend swing when it is materially large
    # in ATR terms on both sides.  This catches fast H4 corrections that a wide
    # pivot wing can miss (for example a sharp 3-5 candle rally inside a new
    # bearish cycle) without importing H1 structure.
    opposite = "HIGH" if wanted_kind == "LOW" else "LOW"
    for p in raw_pivots:
        if p.index < cycle_start or p.kind != wanted_kind or _pivot_is_wick_dominated(bars, p):
            continue
        prev = [q for q in raw_pivots if q.kind == opposite and q.index < p.index]
        fut = [q for q in raw_pivots if q.kind == opposite and q.index > p.index]
        if not prev or not fut:
            continue
        left = prev[-1]
        right = fut[0]
        atr_here = max(atr[p.index], 1e-12)
        left_move = abs(p.price - left.price) / atr_here
        right_move = abs(p.price - right.price) / atr_here
        if left_move >= 1.75 and right_move >= 1.75 and (right.index - left.index) >= 4:
            expanded.add(p.index)
    return expanded


def _retrospective_h4_chain_filter(
    bars: list[dict[str, Any]],
    chain: list[ResearchPivot],
    audits: list[CorrectionAudit],
    trend: str,
) -> list[ResearchPivot]:
    """Demote locally-deep corrections that become minor at the completed H4 scale.

    A correction can look >38.2% while the impulse is still short, then become a
    minor internal pullback after the directional leg extends materially.  For the
    current structural interpretation, compare the original correction excursion
    with the eventual leg from that candidate pivot to the latest directional
    extreme.  This preserves genuinely strategic corrections while preventing a
    later H1-sized pullback from replacing the H4 origin.
    """
    if len(chain) < 2:
        return chain
    promoted = {a.pivot_index: a for a in audits if a.promoted}
    kept = [chain[0]]
    for p in chain[1:]:
        a = promoted.get(p.index)
        if a is None:
            kept.append(p)
            continue
        if trend == "BULLISH":
            prior_endpoint = bars[a.endpoint_index]["high"]
            eventual_endpoint = max(b["high"] for b in bars[p.index:])
        else:
            prior_endpoint = bars[a.endpoint_index]["low"]
            eventual_endpoint = min(b["low"] for b in bars[p.index:])
        correction_excursion = abs(p.price - prior_endpoint)
        eventual_leg = abs(eventual_endpoint - p.price)
        final_depth = correction_excursion / max(eventual_leg, 1e-12)
        if final_depth >= FIB_CANDIDATE_MIN:
            kept.append(p)
        else:
            a.promoted = False
            a.quality.qualified = False
            a.quality.reason = "DEMOTED_TO_INTERNAL_AFTER_H4_IMPULSE_EXTENSION"
    return kept



def _h4_backward_strategic_origin(
    bars: list[dict[str, Any]],
    atr: list[float],
    raw_pivots: list[ResearchPivot],
    trend: str,
) -> ResearchPivot | None:
    """Reconstruct the active H4 impulse backward from the current extreme.

    Atlas teaching rule: the current H4 impulse is not the oldest macro swing and
    not the latest local swing.  Starting from the current directional extreme,
    prefer the most recent *developed H4 structural pivot zone* that launched the
    continuing move.  Repeated reactions must be separated by an opposite swing
    and must persist long enough to represent H4 structure rather than H1 noise.
    A fast single correction is allowed only when the preceding H4 impulse is
    unusually large in ATR terms and the correction itself qualifies structurally.
    """
    if len(bars) < 60:
        return None
    origin_kind = "LOW" if trend == "BULLISH" else "HIGH"
    endpoint_kind = "HIGH" if trend == "BULLISH" else "LOW"

    # Work on the recent H4 teaching horizon only.  The endpoint is the current
    # directional extreme; candidates after it are current correction/range, not
    # origins of the last completed/active impulse.
    start = max(0, len(bars) - 180)
    if trend == "BULLISH":
        endpoint_index = max(range(start, len(bars)), key=lambda i: bars[i]["high"])
    else:
        endpoint_index = min(range(start, len(bars)), key=lambda i: bars[i]["low"])
    if endpoint_index <= start + 4:
        return None

    pts = [
        p for p in raw_pivots
        if p.kind == origin_kind and start <= p.index < endpoint_index and not _pivot_is_wick_dominated(bars, p)
    ]
    opposite = "HIGH" if origin_kind == "LOW" else "LOW"

    # Cluster repeated reactions into ATR-normalized strategic zones.  The wider
    # 1.0 ATR band is intentional: broker feeds can differ slightly while the
    # structural support/resistance event remains the same.
    zones: list[dict[str, Any]] = []
    for p in pts:
        tol = 1.0 * max(atr[p.index], 1e-12)
        best = None
        best_dist = None
        for z in zones:
            dist = abs(p.price - z["center"])
            if p.index - z["touches"][-1].index <= 24 and dist <= max(tol, z["tol"]):
                if best_dist is None or dist < best_dist:
                    best, best_dist = z, dist
        if best is None:
            zones.append({"center": p.price, "tol": tol, "touches": [p]})
        else:
            best["touches"].append(p)
            best["center"] = sum(x.price for x in best["touches"]) / len(best["touches"])
            best["tol"] = max(best["tol"], tol)

    developed: list[ResearchPivot] = []
    for z in zones:
        touches = z["touches"]
        if len(touches) < 2:
            continue
        first = touches[0]
        confirm_pos = None
        for pos, t in enumerate(touches[1:], start=1):
            separated = any(first.index < q.index < t.index and q.kind == opposite for q in raw_pivots)
            if t.index - first.index >= 4 and separated:
                confirm_pos = pos
                break
        if confirm_pos is None:
            continue
        # H4-scale persistence gate.  A compact lower-timeframe-looking cluster is
        # not enough to reset the H4 impulse.
        if touches[-1].index - first.index < 24:
            continue
        tail = touches[confirm_pos:]
        rep = min(tail, key=lambda x: x.price) if trend == "BULLISH" else max(tail, key=lambda x: x.price)
        if rep.index >= endpoint_index:
            continue
        atr_here = max(atr[rep.index], 1e-12)
        endpoint_price = bars[endpoint_index]["high" if trend == "BULLISH" else "low"]
        displacement = abs(endpoint_price - rep.price) / atr_here
        if displacement < 3.0:
            continue
        rep = ResearchPivot(rep.index, rep.time, rep.price, rep.kind, True, "H4_BACKWARD_DEVELOPED_STRATEGIC_ZONE")
        developed.append(rep)

    developed_pick = None
    if developed:
        ordered = sorted(developed, key=lambda p: p.index)
        developed_pick = ordered[-1]
        endpoint_price = bars[endpoint_index]["high" if trend == "BULLISH" else "low"]
        # Walk backward if the newest developed zone is only an internal pullback
        # when measured against the fully extended H4 leg from the prior zone.
        for prev in reversed(ordered[:-1]):
            separation_atr = abs(developed_pick.price - prev.price) / max(atr[developed_pick.index], 1e-12)
            if separation_atr >= 4.0:
                break
            between = bars[prev.index:developed_pick.index + 1]
            if not between:
                continue
            if trend == "BULLISH":
                running_extreme = max(b["high"] for b in between)
                correction_excursion = max(0.0, running_extreme - developed_pick.price)
            else:
                running_extreme = min(b["low"] for b in between)
                correction_excursion = max(0.0, developed_pick.price - running_extreme)
            eventual_leg = abs(endpoint_price - prev.price)
            retrospective_depth = correction_excursion / max(eventual_leg, 1e-12)
            if retrospective_depth < FIB_CANDIDATE_MIN:
                developed_pick = prev
            else:
                break

    # Fallback for a fast but genuine H4 correction: scan backward from the current
    # extreme and accept the latest correction whose local quality is valid *and*
    # whose preceding directional leg is large in H4 ATR terms.
    pivots = _compress_alternating(raw_pivots)
    for p in reversed([x for x in pivots if x.kind == origin_kind and start <= x.index < endpoint_index]):
        prev_ep = [q for q in pivots if q.kind == endpoint_kind and q.index < p.index]
        if not prev_ep:
            continue
        ep = prev_ep[-1]
        prev_o = [q for q in pivots if q.kind == origin_kind and q.index < ep.index]
        if not prev_o:
            continue
        o = prev_o[-1]
        q = _correction_quality(bars, atr, impulse_origin=o, impulse_endpoint=ep, correction_pivot=p, trend=trend)
        prior_leg_atr = abs(ep.price - o.price) / max(atr[ep.index], 1e-12)
        continuation = (
            bars[endpoint_index]["high"] > ep.price if trend == "BULLISH"
            else bars[endpoint_index]["low"] < ep.price
        )
        if q.qualified and prior_leg_atr >= 5.5 and continuation and not _pivot_is_wick_dominated(bars, p):
            fast = ResearchPivot(p.index, p.time, p.price, p.kind, True, "H4_BACKWARD_FAST_STRATEGIC_CORRECTION")
            if developed_pick is None or fast.index > developed_pick.index:
                return fast
            break
    return developed_pick

def analyze_structure(
    raw_bars: Iterable[Any],
    *,
    symbol: str = "UNKNOWN",
    timeframe: str = "H4",
    wing: int | None = None,
) -> StructureResearchResult:
    bars = _bars(raw_bars)
    if len(bars) < 40:
        raise ValueError("Structure v2 requires at least 40 completed bars")
    tf = timeframe.upper()
    wing = wing if wing is not None else {"H4": 2, "H1": 3, "M15": 3, "M5": 4}.get(tf, 3)
    atr = _atr(bars)
    raw_pivots = _local_pivots(bars, wing)
    pivots = _compress_alternating(raw_pivots)
    notes: list[str] = [
        "Fibonacci 38.2% is a candidate-depth gate, never an automatic strategic-pivot promotion.",
        "A strategic correction must move beyond 38.2% with candle-body/close acceptance, not wick-only penetration.",
        "A strategic correction must show multi-candle countertrend development and meaningful body displacement.",
        "Later local HL/LH pivots cannot replace the active strategic origin unless the correction is qualified against the full active impulse.",
        "Trendline interaction is supporting evidence; exact-touch geometry is not required.",
    ]
    if len(pivots) < 4:
        return StructureResearchResult(symbol, tf, "UNRESOLVED", "RANGE", "NONE", None, None, None, [], pivots, None, 0, [], notes+["Too few pivots."])

    cycle_lookback = min(CYCLE_LOOKBACK.get(tf, 320), len(bars))
    cycle_start = max(0, len(bars) - cycle_lookback)
    if tf == "H4":
        bull_scale = _h4_macro_promotion_indices(bars, atr, raw_pivots, "BULLISH", cycle_start=cycle_start)
        bear_scale = _h4_macro_promotion_indices(bars, atr, raw_pivots, "BEARISH", cycle_start=cycle_start)
        bull_chain, bull_audit = _build_persistent_chain(
            bars, atr, pivots, "BULLISH", cycle_start=cycle_start,
            promotion_indices=bull_scale, require_continuation_confirmation=True,
        )
        bear_chain, bear_audit = _build_persistent_chain(
            bars, atr, pivots, "BEARISH", cycle_start=cycle_start,
            promotion_indices=bear_scale, require_continuation_confirmation=True,
        )
        notes.append("H4 strategic hierarchy is macro-first: H1-sized/local corrections cannot reset the H4 impulse origin.")
        notes.append("A qualified H4 correction becomes a new strategic HL/LH only after continuation makes a fresh HH/LL beyond the prior endpoint.")
    else:
        bull_chain, bull_audit = _build_persistent_chain(bars, atr, pivots, "BULLISH", cycle_start=cycle_start)
        bear_chain, bear_audit = _build_persistent_chain(bars, atr, pivots, "BEARISH", cycle_start=cycle_start)
    if tf == "H4":
        bull_chain = _retrospective_h4_chain_filter(bars, bull_chain, bull_audit, "BULLISH")
        bear_chain = _retrospective_h4_chain_filter(bars, bear_chain, bear_audit, "BEARISH")
        notes.append("H4 re-evaluates promoted corrections after impulse extension; a pullback that becomes <38.2% of the eventual H4 leg is demoted back to internal structure.")
    notes.append(f"Current-cycle bootstrap limited to the most recent {cycle_lookback} {tf} bars; obsolete historical cycles cannot seed the active origin.")
    notes.append("Later pivots inside an ATR-normalized strategic pivot zone are treated as retests, not new HL/LH origins.")

    broad = _broad_direction(bars)
    # Prefer the broad timeframe-local direction, but require at least one coherent strategic chain.
    if broad == "BULLISH" and bull_chain:
        dominant = "BULLISH"
    elif broad == "BEARISH" and bear_chain:
        dominant = "BEARISH"
    elif len(bull_chain) > len(bear_chain):
        dominant = "BULLISH"
    elif len(bear_chain) > len(bull_chain):
        dominant = "BEARISH"
    else:
        dominant = broad

    chain = bull_chain if dominant == "BULLISH" else bear_chain
    audit = bull_audit if dominant == "BULLISH" else bear_audit
    origin = chain[-1] if chain else None
    zone_origin = (
        _current_cycle_zone_origin(
            bars, atr, raw_pivots, dominant, cycle_start=cycle_start,
            min_reaction_gap=6 if tf == "H4" else 3,
            max_episode_gap=48 if tf == "H4" else None,
        )
        if dominant in {"BULLISH", "BEARISH"} else None
    )
    if zone_origin is not None and (origin is None or zone_origin.index > origin.index):
        # A zone formed after the last strategic extreme is a correction/range,
        # not a new impulse origin, until continuation makes a fresh HH/LL beyond
        # the pre-zone extreme.
        prior_segment = bars[cycle_start:zone_origin.index]
        future_segment = bars[zone_origin.index + 1:]
        continuation_ok = False
        zone_scale_ok = True
        if prior_segment and future_segment:
            if dominant == "BULLISH":
                prior_extreme = max(b["high"] for b in prior_segment)
                future_extreme = max(b["high"] for b in future_segment)
                continuation_ok = future_extreme > prior_extreme
                # Measure the zone correction against the eventual H4 leg.
                correction_excursion = max(0.0, prior_extreme - zone_origin.price)
                eventual_leg = max(0.0, future_extreme - zone_origin.price)
            else:
                prior_extreme = min(b["low"] for b in prior_segment)
                future_extreme = min(b["low"] for b in future_segment)
                continuation_ok = future_extreme < prior_extreme
                correction_excursion = max(0.0, zone_origin.price - prior_extreme)
                eventual_leg = max(0.0, zone_origin.price - future_extreme)
            if tf == "H4":
                zone_scale_ok = correction_excursion / max(eventual_leg, 1e-12) >= 0.35
        if continuation_ok and zone_scale_ok:
            origin = zone_origin
            chain = [p for p in chain if p.index < zone_origin.index]
            chain.append(zone_origin)
            notes.append("Active origin selected from a repeated current-cycle strategic pivot zone after fresh-extreme continuation; later same-zone retests do not reset it.")
        else:
            notes.append("A later repeated pivot zone stays internal/current correction unless it produces a fresh extreme and remains H4-scale after the impulse extends.")
    if tf == "H4" and dominant in {"BULLISH", "BEARISH"}:
        backward_origin = _h4_backward_strategic_origin(bars, atr, raw_pivots, dominant)
        if backward_origin is not None:
            origin = backward_origin
            chain = [p for p in chain if p.index < backward_origin.index]
            chain.append(backward_origin)
            notes.append("H4 active impulse reconstructed backward from the current strategic extreme; developed H4 zones outrank both stale macro origins and compact H1-scale pullbacks.")

    control = origin
    endpoint = None
    current_corr = None

    if origin:
        if dominant == "BULLISH":
            segment = [(i, b["high"]) for i, b in enumerate(bars) if i >= origin.index]
            if segment:
                i, px = max(segment, key=lambda x: x[1])
                endpoint = ResearchPivot(i, bars[i]["time"], px, "HIGH", True, "CURRENT_EXTREME")
                lows = [p for p in pivots if p.kind == "LOW" and endpoint.index < p.index]
                if lows:
                    current_corr = _correction_quality(bars, atr, impulse_origin=origin, impulse_endpoint=endpoint, correction_pivot=lows[-1], trend="BULLISH")
        elif dominant == "BEARISH":
            segment = [(i, b["low"]) for i, b in enumerate(bars) if i >= origin.index]
            if segment:
                i, px = min(segment, key=lambda x: x[1])
                endpoint = ResearchPivot(i, bars[i]["time"], px, "LOW", True, "CURRENT_EXTREME")
                highs = [p for p in pivots if p.kind == "HIGH" and endpoint.index < p.index]
                if highs:
                    current_corr = _correction_quality(bars, atr, impulse_origin=origin, impulse_endpoint=endpoint, correction_pivot=highs[-1], trend="BEARISH")

    regime = "IMPULSE"
    transition = "NONE"
    if current_corr and current_corr.qualified:
        regime = "CORRECTION"
    if control and endpoint:
        recent = bars[-6:]
        if dominant == "BULLISH":
            below = [b for b in recent if b["close"] < control.price]
            if below:
                transition = "BEARISH_REVERSAL_DEVELOPING" if len(below) >= 2 else "BEARISH_CHOCH_WARNING"
                regime = "TRANSITION"
        elif dominant == "BEARISH":
            above = [b for b in recent if b["close"] > control.price]
            if above:
                transition = "BULLISH_REVERSAL_DEVELOPING" if len(above) >= 2 else "BULLISH_CHOCH_WARNING"
                regime = "TRANSITION"
    if regime == "IMPULSE" and endpoint and endpoint.index < len(bars)-8:
        regime = "RANGE"
        notes.append(f"Range inherits dominant {dominant.lower()} trend until the strategic control pivot is decisively broken and opposite structure develops.")

    strategic = list(chain)
    if endpoint:
        strategic.append(endpoint)
    strategic = sorted({(p.index, p.kind): p for p in strategic}.values(), key=lambda p: p.index)
    strategic_keys = {(x.index, x.kind) for x in strategic}
    internal = [p for p in pivots if (p.index, p.kind) not in strategic_keys]
    anchor_count = len(chain)
    if anchor_count >= 2 and _trendline_supports(chain, atr[-1], dominant):
        notes.append("At least two coherent strategic trendline anchors are available.")

    return StructureResearchResult(
        symbol, tf, dominant, regime, transition, origin, endpoint, control,
        strategic, internal, current_corr, anchor_count, audit, notes,
    )
