from pathlib import Path

def test_observer_passes_h4_effective_direction_to_strategy_gate():
    text=(Path(__file__).resolve().parents[1]/"run_m15_first_observer.py").read_text(encoding="utf-8")
    assert 'snap.h4.get("effective_direction",snap.h4.get("trend","UNAVAILABLE"))' in text
