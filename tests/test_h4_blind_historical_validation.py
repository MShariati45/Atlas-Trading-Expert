from datetime import datetime, timedelta, timezone
from run_h4_blind_historical_validation import choose_blind_cutoffs, _snapshot, _write_full_context, _write_window


def _bars(n=900):
    out=[]
    p=100.0
    for i in range(n):
        # deterministic alternating drift with enough structure for the research detector
        drift = 0.18 if (i // 80) % 2 == 0 else -0.11
        o=p
        c=p+drift
        h=max(o,c)+0.08
        l=min(o,c)-0.08
        t=(datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(hours=4*i)).isoformat()
        out.append({"time":t,"open":o,"high":h,"low":l,"close":c})
        p=c
    return out


def test_cutoffs_exclude_current_teaching_holdout():
    cuts=choose_blind_cutoffs(2200,cases=5,min_history=650,holdout_bars=180)
    assert len(cuts)==5
    assert cuts[0] >= 650
    assert cuts[-1] <= 2020
    assert cuts == sorted(cuts)


def test_cutoffs_fail_closed_when_history_too_short():
    assert choose_blind_cutoffs(700,cases=5,min_history=650,holdout_bars=180) == []


def test_snapshot_is_causal_and_never_uses_future_bars():
    rows=_bars(900)
    cutoff=700
    snap=_snapshot("TEST",rows,cutoff)
    assert snap["bars_available"] == cutoff
    assert snap["cutoff_time"] == rows[cutoff-1]["time"]
    assert snap["anti_lookahead_ok"] is True
    if snap["origin_time"]:
        assert snap["origin_time"] <= snap["cutoff_time"]
    if snap["endpoint_time"]:
        assert snap["endpoint_time"] <= snap["cutoff_time"]


def test_full_context_export_contains_exact_causal_prefix(tmp_path):
    rows=_bars(900)
    cutoff=700
    full=tmp_path / "full.csv"
    compact=tmp_path / "compact.csv"
    _write_full_context(rows, full, cutoff)
    _write_window(rows, compact, cutoff, before=180, after=0)
    full_lines=full.read_text(encoding="utf-8").splitlines()
    compact_lines=compact.read_text(encoding="utf-8").splitlines()
    assert len(full_lines) == cutoff + 1  # header + exact causal prefix
    assert len(compact_lines) == 181      # header + 180 bars
    assert rows[cutoff-1]["time"] in full_lines[-1]
    assert rows[cutoff-1]["time"] in compact_lines[-1]
    assert rows[cutoff]["time"] not in full.read_text(encoding="utf-8")
