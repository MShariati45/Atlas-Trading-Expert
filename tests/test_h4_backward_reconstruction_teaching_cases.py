import csv
from pathlib import Path
from atlas.research.structure_v2 import analyze_structure

ROOT = Path(__file__).resolve().parents[1] / "research_archive" / "h4_teaching_cases"

CASES = {
    "EURUSD": ("EURUSD_H4_2026-07-10_to_2026-08-21.csv", "BULLISH", 1.15124, 1.17108, 0.0020, 0.0015, {"IMPULSE", "CORRECTION", "RANGE"}),
    "USDJPY": ("USDJPY_H4_2026-07-10_to_2026-08-21.csv", "BEARISH", 160.388, 155.235, 0.60, 0.45, {"CORRECTION", "RANGE"}),
    "USDCAD": ("USDCAD_H4_2026-07-10_to_2026-08-21.csv", "BEARISH", 1.41273, 1.37312, 0.0030, 0.0020, {"IMPULSE"}),
    "XAUUSD": ("XAUUSD_H4_2026-07-10_to_2026-08-21.csv", "BULLISH", 4310.66, 4630.0, 20.0, 35.0, {"IMPULSE"}),
}


def _load(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_h4_backward_teaching_cases_all_pass():
    for symbol, (name, trend, origin, endpoint, otol, etol, regimes) in CASES.items():
        result = analyze_structure(_load(ROOT / name), symbol=symbol, timeframe="H4")
        assert result.dominant_trend == trend
        assert result.impulse_origin is not None
        assert result.impulse_endpoint is not None
        assert abs(result.impulse_origin.price - origin) <= otol
        assert abs(result.impulse_endpoint.price - endpoint) <= etol
        assert result.regime in regimes


def test_gold_origin_is_aug14_structural_event():
    result = analyze_structure(_load(ROOT / CASES["XAUUSD"][0]), symbol="XAUUSD", timeframe="H4")
    assert result.impulse_origin.time.startswith("2026-08-14")
    assert result.impulse_origin.reason == "H4_BACKWARD_DEVELOPED_STRATEGIC_ZONE"


def test_usdjpy_origin_is_fast_h4_correction_before_current_range():
    result = analyze_structure(_load(ROOT / CASES["USDJPY"][0]), symbol="USDJPY", timeframe="H4")
    assert result.impulse_origin.time.startswith("2026-07-31")
    assert result.impulse_origin.reason == "H4_BACKWARD_FAST_STRATEGIC_CORRECTION"


def test_usdcad_later_shallow_zone_does_not_reset_origin():
    result = analyze_structure(_load(ROOT / CASES["USDCAD"][0]), symbol="USDCAD", timeframe="H4")
    assert result.impulse_origin.time.startswith("2026-07-28")
    assert result.impulse_origin.price > 1.41
