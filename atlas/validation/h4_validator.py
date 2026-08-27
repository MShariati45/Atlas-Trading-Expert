
from __future__ import annotations
import csv, json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

@dataclass
class Swing:
    index: int
    time: str
    price: float
    kind: str  # HIGH / LOW

@dataclass
class H4Event:
    time: str
    event: str
    reason: str
    price: float | None = None
    retracement_pct: float | None = None

@dataclass
class H4ValidationResult:
    symbol: str
    bars: int
    current_trend: str
    phase: str
    strategic_origin: dict | None
    strategic_endpoint: dict | None
    control_pivot: dict | None
    events: list
    swings: list
    trendline_analysis: dict | None = None

def _read_csv(path: Path):
    rows=[]
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "time": r.get("time") or r.get("time_utc") or r.get("datetime") or "",
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"])
            })
    return rows

def _atr(bars, period=14):
    if len(bars)<2: return 0.0
    trs=[]
    prev=bars[0]["close"]
    for b in bars[1:]:
        trs.append(max(b["high"]-b["low"], abs(b["high"]-prev), abs(b["low"]-prev)))
        prev=b["close"]
    if not trs: return 0.0
    sample=trs[-period:] if len(trs)>=period else trs
    return sum(sample)/len(sample)

def detect_swings(bars, wing=2, atr_mult=0.25):
    swings=[]
    atr=_atr(bars)
    min_sep=max(atr*atr_mult, 1e-12)
    for i in range(wing, len(bars)-wing):
        h=bars[i]["high"]; l=bars[i]["low"]
        left=bars[i-wing:i]; right=bars[i+1:i+1+wing]
        if h>=max(x["high"] for x in left+right):
            if not swings or abs(h-swings[-1].price)>=min_sep or swings[-1].kind!="HIGH":
                swings.append(Swing(i,bars[i]["time"],h,"HIGH"))
        if l<=min(x["low"] for x in left+right):
            if not swings or abs(l-swings[-1].price)>=min_sep or swings[-1].kind!="LOW":
                swings.append(Swing(i,bars[i]["time"],l,"LOW"))
    swings.sort(key=lambda s:s.index)
    # Compress same-type consecutive swings by retaining the more extreme.
    out=[]
    for s in swings:
        if out and out[-1].kind==s.kind:
            if (s.kind=="HIGH" and s.price>=out[-1].price) or (s.kind=="LOW" and s.price<=out[-1].price):
                out[-1]=s
        else:
            out.append(s)
    return out

def _pct_retrace(origin, endpoint, pullback, direction):
    span=abs(endpoint-origin)
    if span<=0: return 0.0
    if direction=="BULLISH":
        return max(0.0, (endpoint-pullback)/span*100.0)
    return max(0.0, (pullback-endpoint)/span*100.0)

def _run_structure(swings):
    """Interpret raw alternating swings as Atlas strategic H4 structure.

    A control-pivot break enters TRANSITION.  Transition keeps consuming swings:
    the old trend can resume by breaking its prior endpoint, or the opposite trend
    is confirmed only after a corrective pivot and continuation beyond the
    reversal break extreme.  This prevents REVERSAL_CANDIDATE from becoming a
    terminal state.
    """
    events=[]
    trend="UNRESOLVED"; phase="UNINITIALIZED"
    origin=endpoint=control=None
    start=len(swings)
    for j in range(3, len(swings)):
        a,b,c,d=swings[j-3:j+1]
        if [x.kind for x in (a,b,c,d)]==["LOW","HIGH","LOW","HIGH"] and c.price>a.price and d.price>b.price:
            trend="BULLISH"; phase="BULLISH_IMPULSE"; origin=a; endpoint=d; control=c
            events.append(H4Event(d.time,"NEW_TREND_CONFIRMED","BOOTSTRAP_HH_HL_SEQUENCE",d.price)); start=j+1; break
        if [x.kind for x in (a,b,c,d)]==["HIGH","LOW","HIGH","LOW"] and c.price<a.price and d.price<b.price:
            trend="BEARISH"; phase="BEARISH_IMPULSE"; origin=a; endpoint=d; control=c
            events.append(H4Event(d.time,"NEW_TREND_CONFIRMED","BOOTSTRAP_LL_LH_SEQUENCE",d.price)); start=j+1; break

    candidate=None
    prior_trend=None
    transition_base=None
    transition_break=None
    reversal_pivot=None

    for s in swings[start:]:
        if trend=="TRANSITION":
            if prior_trend=="BEARISH":
                # A fresh LL before bullish confirmation proves bearish continuation.
                if s.kind=="LOW" and endpoint and s.price < endpoint.price:
                    endpoint=s; trend="BEARISH"; phase="BEARISH_IMPULSE"; candidate=None
                    events.append(H4Event(s.time,"REVERSAL_CANDIDATE_FAILED","OLD_BEARISH_TREND_RESUMED_NEW_LL",s.price))
                    prior_trend=transition_base=transition_break=reversal_pivot=None
                    continue
                if s.kind=="HIGH" and reversal_pivot and transition_break and s.price > transition_break.price:
                    origin=reversal_pivot; control=reversal_pivot; endpoint=s
                    trend="BULLISH"; phase="BULLISH_IMPULSE"; candidate=None
                    events.append(H4Event(s.time,"NEW_TREND_CONFIRMED","REVERSAL_HL_THEN_HH_CONFIRMED",s.price))
                    prior_trend=transition_base=transition_break=reversal_pivot=None
                    continue
                if s.kind=="HIGH" and transition_break and s.price > transition_break.price:
                    transition_break=s
                    events.append(H4Event(s.time,"REVERSAL_EXTREME_EXTENDED","BULLISH_REVERSAL_HIGH_EXTENDED",s.price))
                    continue
                if s.kind=="LOW" and transition_base and s.price > transition_base.price:
                    reversal_pivot=s; phase="BULLISH_REVERSAL_HL_CANDIDATE"
                    events.append(H4Event(s.time,"REVERSAL_CORRECTION_CANDIDATE","HIGHER_LOW_AFTER_BEARISH_CHOCH",s.price))
                    continue
            elif prior_trend=="BULLISH":
                if s.kind=="HIGH" and endpoint and s.price > endpoint.price:
                    endpoint=s; trend="BULLISH"; phase="BULLISH_IMPULSE"; candidate=None
                    events.append(H4Event(s.time,"REVERSAL_CANDIDATE_FAILED","OLD_BULLISH_TREND_RESUMED_NEW_HH",s.price))
                    prior_trend=transition_base=transition_break=reversal_pivot=None
                    continue
                if s.kind=="LOW" and reversal_pivot and transition_break and s.price < transition_break.price:
                    origin=reversal_pivot; control=reversal_pivot; endpoint=s
                    trend="BEARISH"; phase="BEARISH_IMPULSE"; candidate=None
                    events.append(H4Event(s.time,"NEW_TREND_CONFIRMED","REVERSAL_LH_THEN_LL_CONFIRMED",s.price))
                    prior_trend=transition_base=transition_break=reversal_pivot=None
                    continue
                if s.kind=="LOW" and transition_break and s.price < transition_break.price:
                    transition_break=s
                    events.append(H4Event(s.time,"REVERSAL_EXTREME_EXTENDED","BEARISH_REVERSAL_LOW_EXTENDED",s.price))
                    continue
                if s.kind=="HIGH" and transition_base and s.price < transition_base.price:
                    reversal_pivot=s; phase="BEARISH_REVERSAL_LH_CANDIDATE"
                    events.append(H4Event(s.time,"REVERSAL_CORRECTION_CANDIDATE","LOWER_HIGH_AFTER_BULLISH_CHOCH",s.price))
                    continue
            continue

        if trend=="BULLISH":
            if s.kind=="HIGH" and endpoint and s.price>endpoint.price:
                if candidate:
                    control=candidate; origin=candidate; endpoint=s; candidate=None
                    events.append(H4Event(s.time,"VALIDATED_BY_CONTINUATION_BOS","CANDIDATE_HL_VALIDATED_AFTER_NEW_HH",s.price))
                else:
                    endpoint=s; events.append(H4Event(s.time,"STRATEGIC_ENDPOINT_EXTENDED","NEW_HIGH_EXTENDS_ACTIVE_IMPULSE",s.price))
                phase="BULLISH_IMPULSE"
            elif s.kind=="LOW" and origin and endpoint:
                retr=_pct_retrace(origin.price,endpoint.price,s.price,"BULLISH")
                if retr < 38.2:
                    events.append(H4Event(s.time,"INTERNAL_PULLBACK","INTERNAL_LT_38_2",s.price,round(retr,2)))
                else:
                    candidate=s; phase="BULLISH_CORRECTION"
                    events.append(H4Event(s.time,"STRATEGIC_CORRECTION_QUALIFIED","RETRACEMENT_GE_38_2",s.price,round(retr,2)))
                if control and s.price < control.price:
                    prior_trend="BULLISH"; transition_base=endpoint; transition_break=s; reversal_pivot=None
                    phase="BULLISH_REVERSAL_CANDIDATE"; trend="TRANSITION"; candidate=None
                    events.append(H4Event(s.time,"CONTROL_PIVOT_BROKEN_CHOCH","SWING_BELOW_VALIDATED_HL",s.price))
        elif trend=="BEARISH":
            if s.kind=="LOW" and endpoint and s.price<endpoint.price:
                if candidate:
                    control=candidate; origin=candidate; endpoint=s; candidate=None
                    events.append(H4Event(s.time,"VALIDATED_BY_CONTINUATION_BOS","CANDIDATE_LH_VALIDATED_AFTER_NEW_LL",s.price))
                else:
                    endpoint=s; events.append(H4Event(s.time,"STRATEGIC_ENDPOINT_EXTENDED","NEW_LOW_EXTENDS_ACTIVE_IMPULSE",s.price))
                phase="BEARISH_IMPULSE"
            elif s.kind=="HIGH" and origin and endpoint:
                retr=_pct_retrace(origin.price,endpoint.price,s.price,"BEARISH")
                if retr < 38.2:
                    events.append(H4Event(s.time,"INTERNAL_PULLBACK","INTERNAL_LT_38_2",s.price,round(retr,2)))
                else:
                    candidate=s; phase="BEARISH_CORRECTION"
                    events.append(H4Event(s.time,"STRATEGIC_CORRECTION_QUALIFIED","RETRACEMENT_GE_38_2",s.price,round(retr,2)))
                if control and s.price > control.price:
                    prior_trend="BEARISH"; transition_base=endpoint; transition_break=s; reversal_pivot=None
                    phase="BEARISH_REVERSAL_CANDIDATE"; trend="TRANSITION"; candidate=None
                    events.append(H4Event(s.time,"CONTROL_PIVOT_BROKEN_CHOCH","SWING_ABOVE_VALIDATED_LH",s.price))
    return trend, phase, origin, endpoint, control, events



def _trendline_price_index(a: Swing, b: Swing, idx: int) -> float:
    if b.index == a.index:
        return b.price
    slope = (b.price - a.price) / (b.index - a.index)
    return a.price + slope * (idx - a.index)


def _structural_trendline_candidates(bars, swings, formal_trend):
    """Return structurally ranked H4 diagonal lines.

    The line is selected from meaningful same-side swing pivots, not by searching
    for whichever pair happens to create the latest breakout.  A valid bearish
    resistance line should cap intervening swing highs (within tolerance); a
    bullish support line should floor intervening swing lows.  Touches must be
    separated in time so neighboring local pivots cannot inflate quality.
    """
    if formal_trend not in {"BULLISH", "BEARISH"}:
        return []
    kind = "HIGH" if formal_trend == "BEARISH" else "LOW"
    pts = [s for s in swings if s.kind == kind]
    if len(pts) < 2:
        return []

    atr = _atr(bars)
    tolerance = max(atr * 0.30, 1e-6)
    # H4: require meaningful spacing between independent touches.
    min_anchor_span = 6           # minimum 1 trading day; scoring strongly favors longer spans
    min_touch_spacing = 6         # minimum 1 trading day between independent reactions
    max_violation = tolerance * 1.35
    candidates=[]

    # Keep enough history to represent the active regime; do not reduce to the
    # latest handful of pivots because that creates shallow local lines.
    pts = pts[-120:]
    for i in range(len(pts)-1):
        for j in range(i+1, len(pts)):
            a,b=pts[i],pts[j]
            span=b.index-a.index
            if span < min_anchor_span:
                continue
            directional = b.price < a.price if formal_trend=="BEARISH" else b.price > a.price
            if not directional:
                continue

            # A proper resistance/support line must contain the pivots between
            # its anchors.  Large penetrations before the supposed breakout mean
            # this is not the active structural line.
            contained=True
            raw_touches=[]
            for p in pts[i:j+1]:
                lp=_trendline_price_index(a,b,p.index)
                delta=p.price-lp
                if formal_trend=="BEARISH" and delta > max_violation:
                    contained=False; break
                if formal_trend=="BULLISH" and delta < -max_violation:
                    contained=False; break
                if abs(delta) <= tolerance:
                    raw_touches.append(p)
            if not contained:
                continue

            # Independent touches need temporal spacing.
            touched=[]
            for p in raw_touches:
                if not touched or p.index-touched[-1].index >= min_touch_spacing:
                    touched.append(p)
                else:
                    # if two nearby pivots represent one reaction, keep the one
                    # closest to the line rather than counting both.
                    prev=touched[-1]
                    prev_err=abs(prev.price-_trendline_price_index(a,b,prev.index))
                    err=abs(p.price-_trendline_price_index(a,b,p.index))
                    if err < prev_err:
                        touched[-1]=p
            if len(touched) < 2:
                continue

            # Structural score rewards duration, independent reactions and broad
            # spacing. It intentionally does NOT reward whether a breakout later
            # occurred, preventing outcome-driven line selection.
            touch_span=touched[-1].index-touched[0].index
            score=(len(touched)*1000.0) + (span*2.0) + touch_span
            if len(touched) >= 3:
                score += 750.0
            candidates.append((score, span, len(touched), a, b, touched, tolerance))
    candidates.sort(key=lambda x:(x[0],x[1],x[2]), reverse=True)
    return candidates


def analyze_latest_h4_trendline(bars, swings, formal_trend):
    """Diagnostic diagonal-structure analysis for the current formal H4 trend.

    Selection is structural first: use a long-lived line through meaningful,
    well-spaced same-side pivots that contains intervening price structure.
    Only after that line is chosen do we evaluate a close beyond it and the
    required later confirmation candle.
    """
    if formal_trend not in {"BULLISH", "BEARISH"}:
        return {"status": "UNAVAILABLE", "early_direction": "NONE", "reason": "FORMAL_TREND_NOT_DIRECTIONAL"}
    direction = "BULLISH" if formal_trend == "BEARISH" else "BEARISH"
    candidates=_structural_trendline_candidates(bars,swings,formal_trend)
    if not candidates:
        return {"status": "UNAVAILABLE", "early_direction": "NONE", "reason": "NO_VALID_STRUCTURAL_TRENDLINE"}

    score,span,touch_count,a,b,touched,tolerance=candidates[0]
    breakout=None; confirmation=None
    # Evaluate break only AFTER the final structural touch/anchor area.
    search_from=max(p.index for p in touched)+1
    for k in range(search_from, len(bars)):
        lp=_trendline_price_index(a,b,k)
        close=bars[k]["close"]
        beyond = close > lp if direction=="BULLISH" else close < lp
        if breakout is None:
            if beyond:
                breakout=k
            continue
        if k <= breakout:
            continue
        if beyond:
            open_=bars[k]["open"]
            directional = close > open_ if direction=="BULLISH" else close < open_
            follow = close >= bars[breakout]["close"] if direction=="BULLISH" else close <= bars[breakout]["close"]
            if directional or follow:
                confirmation=k
                break
        else:
            breakout=None

    status = "RETIRED" if confirmation is not None else ("BREAKOUT_PENDING" if breakout is not None else "ACTIVE")
    result={
        "status": status,
        "formal_trend": formal_trend,
        "early_direction": direction if confirmation is not None else "NONE",
        "confirmation_status": "EARLY_DIRECTION_CONFIRMED" if confirmation is not None else "NONE",
        "retired_time": bars[confirmation]["time"] if confirmation is not None else None,
        "touch_count": touch_count,
        "quality": "STRONG" if touch_count>=3 else "BASE",
        "selection_method": "STRUCTURAL_LONG_SPAN_WELL_SPACED_TOUCHES",
        "selection_score": round(score,2),
        "anchor_span_bars": span,
        "tolerance": tolerance,
        "anchor_1": {"time":a.time,"price":a.price,"index":a.index,"kind":a.kind},
        "anchor_2": {"time":b.time,"price":b.price,"index":b.index,"kind":b.kind},
        "touch_points": [{"time":p.time,"price":p.price,"index":p.index,"kind":p.kind} for p in touched],
        "breakout": None,
        "confirmation": None,
    }
    if breakout is not None:
        result["breakout"]={"time":bars[breakout]["time"],"close":bars[breakout]["close"],"index":breakout}
    if confirmation is not None:
        result["confirmation"]={"time":bars[confirmation]["time"],"close":bars[confirmation]["close"],"index":confirmation}
    return result

def validate_h4(path: str | Path, symbol: Optional[str]=None) -> H4ValidationResult:
    path=Path(path); bars=_read_csv(path)
    symbol=symbol or path.stem.replace("_H4","")
    swings=detect_swings(bars)
    trend, phase, origin, endpoint, control, events = _run_structure(swings)
    trendline_analysis = analyze_latest_h4_trendline(bars, swings, trend)

    def sw(s):
        return None if s is None else {"time":s.time,"price":s.price,"kind":s.kind,"index":s.index}

    return H4ValidationResult(
        symbol=symbol,bars=len(bars),current_trend=trend,phase=phase,
        strategic_origin=sw(origin),strategic_endpoint=sw(endpoint),control_pivot=sw(control),
        events=[asdict(e) for e in events], swings=[asdict(s) for s in swings],
        trendline_analysis=trendline_analysis
    )

def write_validation(result: H4ValidationResult, out_dir: str | Path):
    out=Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    js=out/f"{result.symbol}_H4_validation.json"
    js.write_text(json.dumps(asdict(result),indent=2),encoding="utf-8")
    return js
