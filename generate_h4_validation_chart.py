
import csv, json, webbrowser
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parent
BARS = ROOT / "historical_data" / "one_year" / "bars" / "EURUSD_H4.csv"
VAL = ROOT / "h4_validation_output" / "EURUSD_H4_validation.json"
OUTDIR = ROOT / "h4_validation_output"
OUT = OUTDIR / "EURUSD_H4_validation_chart.html"

def load_bars():
    rows=[]
    with BARS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "time": r.get("time") or r.get("time_utc") or r.get("datetime") or "",
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })
    return rows

def find_index(bars, t):
    for i,b in enumerate(bars):
        if b["time"] == t:
            return i
    # tolerate timezone formatting mismatch by prefix
    ts=t.replace("+00:00","")
    for i,b in enumerate(bars):
        if b["time"].replace("+00:00","").startswith(ts[:19]):
            return i
    return None

def main():
    if not BARS.exists():
        raise SystemExit(f"Missing {BARS}")
    if not VAL.exists():
        raise SystemExit(
            f"Missing {VAL}\nRun validate_h4_eurusd_windows.bat first."
        )

    bars=load_bars()
    data=json.loads(VAL.read_text(encoding="utf-8"))
    tl=data.get("trendline_analysis") or {}

    # Show recent context around trendline anchors through end of dataset.
    candidate_times=[]
    for key in ("strategic_origin","strategic_endpoint","control_pivot"):
        obj=data.get(key) or {}
        if obj.get("time"): candidate_times.append(obj["time"])
    for key in ("anchor_1","anchor_2","breakout","confirmation"):
        obj=tl.get(key) or {}
        if obj.get("time"): candidate_times.append(obj["time"])

    idxs=[find_index(bars,t) for t in candidate_times]
    idxs=[i for i in idxs if i is not None]
    start=max(0,(min(idxs) if idxs else len(bars)-220)-60)
    end=len(bars)-1
    view=bars[start:end+1]

    W,H=1800,900
    left,right,top,bottom=90,40,70,90
    pw=W-left-right
    ph=H-top-bottom

    lows=[b["low"] for b in view]
    highs=[b["high"] for b in view]
    lo=min(lows); hi=max(highs)
    pad=(hi-lo)*0.08 if hi>lo else 0.01
    lo-=pad; hi+=pad

    def x(global_i):
        return left + ((global_i-start)/(max(1,end-start))) * pw
    def y(price):
        return top + (hi-price)/(hi-lo) * ph

    svg=[]
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    svg.append('<rect width="100%" height="100%" fill="#0b0f14"/>')

    # grid
    for k in range(9):
        yy=top + k*ph/8
        price=hi-k*(hi-lo)/8
        svg.append(f'<line x1="{left}" x2="{W-right}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#25303b" stroke-width="1"/>')
        svg.append(f'<text x="{W-right-5}" y="{yy-5:.1f}" text-anchor="end" fill="#9fb0bf" font-size="16">{price:.5f}</text>')

    step=max(1,int((end-start)/10))
    for gi in range(start,end+1,step):
        xx=x(gi)
        svg.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{top}" y2="{H-bottom}" stroke="#18212a" stroke-width="1"/>')
        label=bars[gi]["time"][:10]
        svg.append(f'<text x="{xx:.1f}" y="{H-bottom+28}" text-anchor="middle" fill="#9fb0bf" font-size="15">{escape(label)}</text>')

    # candles
    candle_w=max(2.0, pw/max(1,len(view))*0.65)
    for gi,b in enumerate(view,start):
        xx=x(gi)
        up=b["close"]>=b["open"]
        col="#34d399" if up else "#f87171"
        svg.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{y(b["high"]):.1f}" y2="{y(b["low"]):.1f}" stroke="{col}" stroke-width="1.2"/>')
        yy1=y(max(b["open"],b["close"])); yy2=y(min(b["open"],b["close"]))
        rh=max(1.5,yy2-yy1)
        svg.append(f'<rect x="{xx-candle_w/2:.1f}" y="{yy1:.1f}" width="{candle_w:.1f}" height="{rh:.1f}" fill="{col}"/>')

    def marker(obj,label,shape="circle"):
        if not obj or not obj.get("time"): return
        gi=find_index(bars,obj["time"])
        if gi is None or gi<start or gi>end: return
        price=float(obj.get("price", obj.get("close", bars[gi]["close"])))
        xx,yy=x(gi),y(price)
        if shape=="diamond":
            pts=f"{xx},{yy-9} {xx+9},{yy} {xx},{yy+9} {xx-9},{yy}"
            svg.append(f'<polygon points="{pts}" fill="#fbbf24" stroke="#ffffff" stroke-width="1.5"/>')
        elif shape=="square":
            svg.append(f'<rect x="{xx-7}" y="{yy-7}" width="14" height="14" fill="#60a5fa" stroke="#fff" stroke-width="1.5"/>')
        else:
            svg.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="8" fill="#22d3ee" stroke="#fff" stroke-width="1.5"/>')
        svg.append(f'<text x="{xx+12:.1f}" y="{yy-10:.1f}" fill="#ffffff" font-size="15">{escape(label)}</text>')

    # formal structure markers
    marker(data.get("strategic_origin"),"Strategic Origin","diamond")
    marker(data.get("strategic_endpoint"),"Strategic Endpoint","diamond")
    marker(data.get("control_pivot"),"Control Pivot","square")

    # trendline anchors
    a1=tl.get("anchor_1") or {}
    a2=tl.get("anchor_2") or {}
    i1=find_index(bars,a1.get("time","")) if a1 else None
    i2=find_index(bars,a2.get("time","")) if a2 else None
    if i1 is not None and i2 is not None and i1!=i2:
        p1=float(a1["price"]); p2=float(a2["price"])
        # Project only while the trendline is active. Once a confirmed break
        # retires it, stop the visual line at the confirmation candle.
        slope=(p2-p1)/(i2-i1)
        line_end=end
        cf_for_line=tl.get("confirmation") or {}
        cf_idx=find_index(bars,cf_for_line.get("time","")) if cf_for_line else None
        if tl.get("status") == "RETIRED" and cf_idx is not None:
            line_end=min(end,cf_idx)
        p_start=p1+slope*(start-i1)
        p_end=p1+slope*(line_end-i1)
        svg.append(f'<line x1="{x(start):.1f}" y1="{y(p_start):.1f}" x2="{x(line_end):.1f}" y2="{y(p_end):.1f}" stroke="#ffffff" stroke-width="2.4"/>')
        marker(a1,"Trendline Anchor 1")
        marker(a2,"Trendline Anchor 2")

        # Use the validator's actual structural touch points so the chart is a
        # faithful explanation of why the line was selected.
        touch_objs=tl.get("touch_points") or []
        for n,tobj in enumerate(touch_objs[:12],1):
            gi=find_index(bars,tobj.get("time",""))
            if gi is None or gi<start or gi>end: continue
            price=float(tobj.get("price",bars[gi]["high"]))
            xx,yy=x(gi),y(price)
            svg.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="12" fill="none" stroke="#22d3ee" stroke-width="3"/>')
            dy=20+(n%2)*18
            svg.append(f'<text x="{xx+14:.1f}" y="{yy+dy:.1f}" fill="#22d3ee" font-size="14">Touch {n}</text>')

    # breakout + confirmation
    bo=tl.get("breakout") or {}
    cf=tl.get("confirmation") or {}
    if bo:
        bo2={"time":bo.get("time"),"price":bo.get("close")}
        marker(bo2,"Breakout","square")
    if cf:
        cf2={"time":cf.get("time"),"price":cf.get("close")}
        marker(cf2,"Confirmation","diamond")

    title=f'EURUSD H4 Atlas Validation — Formal {data.get("current_trend","?")} | Early {tl.get("early_direction","NONE")} | {tl.get("status","NO_TRENDLINE")}'
    svg.append(f'<text x="{left}" y="35" fill="#ffffff" font-size="26" font-weight="bold">{escape(title)}</text>')
    svg.append(f'<text x="{left}" y="58" fill="#a8b3bf" font-size="16">Touches: {tl.get("touch_count","?")} | Quality: {tl.get("quality","?")} | Events: {len(data.get("events",[]))}</text>')
    svg.append('</svg>')

    html=f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Atlas H4 Validation</title>
<style>
body{{margin:0;background:#0b0f14;color:#fff;font-family:Arial,sans-serif}}
.wrap{{padding:16px}}
.card{{background:#111827;border:1px solid #25303b;border-radius:12px;padding:12px;overflow:auto}}
.meta{{margin:10px 0 16px;color:#cbd5e1;line-height:1.5}}
</style></head><body><div class="wrap">
<div class="meta">
<b>Formal H4 trend:</b> {escape(str(data.get("current_trend")))}
&nbsp; | &nbsp;<b>Phase:</b> {escape(str(data.get("phase")))}
&nbsp; | &nbsp;<b>Early direction:</b> {escape(str(tl.get("early_direction")))}
&nbsp; | &nbsp;<b>Trendline status:</b> {escape(str(tl.get("status")))}
</div>
<div class="card">{''.join(svg)}</div>
</div></body></html>"""
    OUTDIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html,encoding="utf-8")
    print(f"Chart created: {OUT}")
    try:
        webbrowser.open(OUT.resolve().as_uri())
    except Exception:
        pass
    input("Press Enter to close...")

if __name__=="__main__":
    main()
