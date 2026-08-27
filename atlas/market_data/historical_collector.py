from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import hashlib
import json
from typing import Iterable

from atlas.execution.models import AccountConfig
from atlas.market_data.mt5_feed import Candle, MT5MarketDataFeed

TIMEFRAMES = ("D1", "H4", "H1", "M15")

@dataclass(slots=True)
class HistoryFileRecord:
    symbol: str
    timeframe: str
    rows: int
    first_bar_utc: str | None
    last_bar_utc: str | None
    file: str
    sha256: str

@dataclass(slots=True)
class HistoryCollectionManifest:
    schema_version: str
    collected_at_utc: str
    requested_start_utc: str
    requested_end_utc: str
    account_id: str
    broker: str
    timeframes: list[str]
    records: list[dict]
    symbol_metadata: dict[str, dict]
    account_snapshot: dict | None
    notes: list[str]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_candles(path: Path, candles: Iterable[Candle]) -> int:
    rows = list(candles)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "open", "high", "low", "close", "tick_volume", "spread_points", "real_volume"])
        for c in rows:
            w.writerow([
                c.time_utc.isoformat(), c.open, c.high, c.low, c.close,
                c.tick_volume, c.spread_points, c.real_volume,
            ])
    return len(rows)


class MT5HistoricalCollector:
    """Collects deterministic, completed-bar MT5 history for Atlas research.

    Collection is read-only. It never sends or modifies orders.
    """

    def __init__(self, feed: MT5MarketDataFeed) -> None:
        self.feed = feed

    @staticmethod
    def one_year_window(end_utc: datetime | None = None) -> tuple[datetime, datetime]:
        end = end_utc or datetime.now(timezone.utc)
        if end.tzinfo is None:
            raise ValueError("end_utc must be timezone-aware")
        # Keep the end safely behind any currently forming M15 candle.
        end = end.astimezone(timezone.utc).replace(second=0, microsecond=0)
        end -= timedelta(minutes=end.minute % 15)
        end -= timedelta(minutes=15)
        return end - timedelta(days=366), end

    def collect(
        self,
        account: AccountConfig,
        symbols: list[str],
        out_dir: str | Path,
        start_utc: datetime,
        end_utc: datetime,
        timeframes: tuple[str, ...] = TIMEFRAMES,
    ) -> HistoryCollectionManifest:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        records: list[dict] = []
        metadata: dict[str, dict] = {}
        notes: list[str] = []
        try:
            account_snap = asdict(self.feed.account_snapshot())
        except Exception as exc:
            account_snap = None
            notes.append(f"ACCOUNT_SNAPSHOT_UNAVAILABLE:{type(exc).__name__}")

        for symbol in symbols:
            info = self.feed.ensure_symbol(symbol)
            metadata[symbol] = asdict(info)
            for tf in timeframes:
                bars = self.feed.bars_range(symbol, tf, start_utc, end_utc)
                file = out / "bars" / f"{symbol}_{tf}.csv"
                n = _write_candles(file, bars)
                rec = HistoryFileRecord(
                    symbol=symbol,
                    timeframe=tf,
                    rows=n,
                    first_bar_utc=bars[0].time_utc.isoformat() if bars else None,
                    last_bar_utc=bars[-1].time_utc.isoformat() if bars else None,
                    file=str(file.relative_to(out)),
                    sha256=_sha256(file),
                )
                records.append(asdict(rec))
                if n == 0:
                    notes.append(f"NO_HISTORY:{symbol}:{tf}")

        manifest = HistoryCollectionManifest(
            schema_version="1.0",
            collected_at_utc=datetime.now(timezone.utc).isoformat(),
            requested_start_utc=start_utc.astimezone(timezone.utc).isoformat(),
            requested_end_utc=end_utc.astimezone(timezone.utc).isoformat(),
            account_id=account.account_id,
            broker=account.broker,
            timeframes=list(timeframes),
            records=records,
            symbol_metadata=metadata,
            account_snapshot=account_snap,
            notes=notes,
        )
        (out / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        return manifest
