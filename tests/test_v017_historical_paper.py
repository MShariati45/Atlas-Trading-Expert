
import json
from pathlib import Path
from atlas.backtest.models import PaperTrade
from atlas.backtest.engine import HistoricalPaperHarness, summarize

def mk(direction="LONG"):
    return PaperTrade("EURUSD","2026-01-01","LONG","IMPULSE_CORRECTION",50.0,"38.2-61.8",
                      1.1000,1.0900,1.1200,96.0,"PAPER_APPROVE")

def test_tp_is_2r():
    t=mk(); bars=[{"time":"x","high":1.121,"low":1.099}]
    r=HistoricalPaperHarness().resolve(t,bars)
    assert r.outcome=="TP" and r.realized_r==2.0

def test_be70_moves_once_then_be():
    t=mk()
    bars=[{"time":"a","high":1.1141,"low":1.099},
          {"time":"b","high":1.115,"low":1.0999}]
    r=HistoricalPaperHarness().resolve(t,bars)
    assert r.be_triggered and r.outcome=="BE" and r.realized_r==0.0

def test_conservative_same_bar_stop_before_target():
    t=mk(); bars=[{"time":"x","high":1.121,"low":1.089}]
    r=HistoricalPaperHarness().resolve(t,bars)
    assert r.outcome=="SL"

def test_summary_by_symbol():
    a=mk(); a.realized_r=2.0
    b=mk(); b.realized_r=-1.0
    s=summarize([a,b])
    assert s["overall"]["trades"]==2 and s["overall"]["net_r"]==1.0

def test_watchlist_frozen_controls_present():
    cfg=json.loads((Path(__file__).parents[1]/"config"/"demo_watchlist.json").read_text())
    assert cfg["risk"]["risk_per_trade_pct"]==0.5
    assert cfg["risk"]["max_trades_per_day"]==2
    assert cfg["management"]["target_r"]==2.0
    assert cfg["management"]["breakeven_trigger_r"]==1.4
    assert cfg["quality"]["minimum_score"]==95
