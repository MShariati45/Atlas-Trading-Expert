from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from atlas.dashboard.live_state import LiveObservationDashboardService
from atlas.market_data.live_runtime import RuntimeSnapshot
from atlas.market_data.mt5_feed import AccountSnapshot, SymbolSnapshot, TickSnapshot


class FakeRuntime:
    def poll_symbol(self, symbol):
        return RuntimeSnapshot(
            symbol=symbol,
            h4={"trend":"BULLISH","phase":"BULLISH_IMPULSE","state_version":3},
            h1={"trend":"BULLISH","phase":"BULLISH_CORRECTION","state_version":7},
            fibonacci={"retracement_pct":47.5,"zone":"FIB_38_2_TO_50","flag_early_access":False,"broad_m15_activation":True},
            last_h4_bar="2026-08-18T20:00:00+00:00", last_h1_bar="2026-08-18T22:00:00+00:00", alignment={"aligned":True,"state":"ALIGNED_BULLISH","direction":"BULLISH"})


class FakeFeed:
    def account_snapshot(self):
        return AccountSnapshot(1,"Demo","USD",10000,10100,100,10000,100,True)
    def positions(self): return []
    def terminal_health(self): return {"terminal_connected":True,"trade_allowed":True}
    def tick(self,symbol): return TickSnapshot(symbol,datetime.now(timezone.utc),1.1,1.1002,0,0)
    def ensure_symbol(self,symbol): return SymbolSnapshot(symbol,0.0001,5,0.00001,1,0.01,100,0.01,0,0,True)
    @staticmethod
    def snapshot_dict(v):
        from dataclasses import asdict
        return asdict(v)


def test_dashboard_builds_broad_m15_state_and_is_read_only():
    with TemporaryDirectory() as d:
        svc=LiveObservationDashboardService(FakeFeed(),FakeRuntime(),Path(d)/"state.json")
        state=svc.write(["EURUSD","GBPUSD"])
        assert state["mode"]=="READ_ONLY_OBSERVATION"
        assert state["execution_enabled"] is False
        assert state["watchlist"][0]["broad_m15"]=="SCANNING"
        assert state["watchlist"][0]["coordinator"]=="WAITING_FOR_M15_REPORTS"
        assert (Path(d)/"state.json").exists()


def test_dashboard_change_detection_is_stateful():
    with TemporaryDirectory() as d:
        svc=LiveObservationDashboardService(FakeFeed(),FakeRuntime(),Path(d)/"state.json")
        first=svc.build(["EURUSD"])
        second=svc.build(["EURUSD"])
        assert first["watchlist"][0]["changed"] is True
        assert second["watchlist"][0]["changed"] is False
