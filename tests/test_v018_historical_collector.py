from datetime import datetime, timezone
from pathlib import Path
import json

from atlas.execution.models import AccountConfig
from atlas.market_data.historical_collector import MT5HistoricalCollector
from atlas.market_data.mt5_feed import Candle, SymbolSnapshot, AccountSnapshot
from atlas.backtest.dataset import audit_dataset


class FakeFeed:
    def account_snapshot(self):
        return AccountSnapshot(123,'Demo','USD',10000,10000,0,10000,100,True)
    def ensure_symbol(self, symbol):
        return SymbolSnapshot(symbol,0.00001,5,0.00001,1.0,0.01,100.0,0.01,0,0,True)
    def bars_range(self, symbol, timeframe, start_utc, end_utc):
        step={'M15':900,'H1':3600,'H4':14400,'D1':86400}[timeframe]
        rows=[]
        t=int(start_utc.timestamp())
        for i in range(12):
            ts=datetime.fromtimestamp(t+i*step,tz=timezone.utc)
            rows.append(Candle(ts,1.0,1.1,0.9,1.05,100,12,0))
        return rows


def test_one_year_window_is_timezone_aware_and_behind_now():
    start,end=MT5HistoricalCollector.one_year_window(datetime(2026,8,18,20,7,tzinfo=timezone.utc))
    assert start.tzinfo is not None and end.tzinfo is not None
    assert end.minute % 15 == 0
    assert end < datetime(2026,8,18,20,7,tzinfo=timezone.utc)


def test_collector_writes_manifest_and_four_timeframes(tmp_path):
    collector=MT5HistoricalCollector(FakeFeed())
    account=AccountConfig('DEMO',True,0.5,2.0,'MT5_DEMO')
    start=datetime(2025,8,1,tzinfo=timezone.utc); end=datetime(2026,8,1,tzinfo=timezone.utc)
    m=collector.collect(account,['EURUSD'],tmp_path,start,end)
    assert len(m.records)==4
    assert (tmp_path/'manifest.json').exists()
    for tf in ('D1','H4','H1','M15'):
        assert (tmp_path/'bars'/f'EURUSD_{tf}.csv').exists()


def test_dataset_audit_detects_missing_manifest(tmp_path):
    audit=audit_dataset(tmp_path)
    assert not audit.ready
    assert audit.issues[0]['code']=='MANIFEST_MISSING'


def test_dataset_audit_accepts_collected_shape(tmp_path):
    collector=MT5HistoricalCollector(FakeFeed())
    account=AccountConfig('DEMO',True,0.5,2.0,'MT5_DEMO')
    start=datetime(2025,8,1,tzinfo=timezone.utc); end=datetime(2026,8,1,tzinfo=timezone.utc)
    collector.collect(account,['EURUSD'],tmp_path,start,end)
    audit=audit_dataset(tmp_path,min_m15_rows=10)
    assert audit.ready
    assert audit.bars_by_symbol['EURUSD']['M15']==12
