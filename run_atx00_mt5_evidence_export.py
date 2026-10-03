"""Read-only MT5 evidence exporter for Atlas ATX-00.

This script never sends, modifies, or closes orders. It requires a MetaTrader 5
terminal that is already logged in. The export is a raw evidence pack, not a
normalized trading decision record and not a production data source.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable


def _parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timestamps must include timezone/UTC")
    return value.astimezone(timezone.utc)


def _jsonable_row(row: Any) -> dict[str, Any]:
    if hasattr(row, "_asdict"):
        data = dict(row._asdict())
    elif isinstance(row, dict):
        data = dict(row)
    elif hasattr(row, "dtype") and getattr(row.dtype, "names", None):
        data = {name: row[name] for name in row.dtype.names}
    else:
        raise TypeError(f"unsupported MT5 row type: {type(row).__name__}")
    result: dict[str, Any] = {}
    for key, value in data.items():
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
        else:
            result[str(key)] = str(value)
    return result


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _indexed_rows(rows: Iterable[Any], *, source_kind: str) -> Iterable[dict[str, Any]]:
    for index, row in enumerate(rows):
        payload = _jsonable_row(row)
        payload["_atlas_source_kind"] = source_kind
        payload["_atlas_api_index"] = index
        yield payload


def _write_jsonl_gz(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    count = 0
    with path.open("wb") as raw:
        with gzip.GzipFile(
            fileobj=raw,
            mode="wb",
            filename="",
            mtime=0,
        ) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(
                        json.dumps(
                            row,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    )
                    f.write("\n")
                    count += 1
    return count, _sha256_file(path)


def _require_connected(mt5: Any) -> tuple[Any, Any]:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None:
        raise RuntimeError(f"MT5 terminal_info failed: {mt5.last_error()}")
    if account is None:
        raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
    if not bool(getattr(terminal, "connected", False)):
        raise RuntimeError("MT5 terminal is not connected")
    return terminal, account


def _write_ticks_by_day(
    path: Path,
    mt5: Any,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> tuple[int, str, list[dict[str, Any]]]:
    flags = getattr(mt5, "COPY_TICKS_ALL")
    chunks: list[dict[str, Any]] = []

    def rows() -> Iterable[dict[str, Any]]:
        for symbol in symbols:
            day = start
            while day < end:
                next_day = min(day + timedelta(days=1), end)
                ticks = mt5.copy_ticks_range(symbol, day, next_day, flags)
                if ticks is None:
                    raise RuntimeError(
                        f"MT5 copy_ticks_range failed for {symbol}: {mt5.last_error()}"
                    )
                first_msc = None
                last_msc = None
                for row_index, row in enumerate(ticks):
                    payload = _jsonable_row(row)
                    time_msc = payload.get("time_msc")
                    if isinstance(time_msc, int):
                        if first_msc is None:
                            first_msc = time_msc
                        last_msc = time_msc
                    payload["_atlas_source_kind"] = "TICK"
                    payload["_atlas_symbol"] = symbol
                    payload["_atlas_chunk_row_index"] = row_index
                    payload["_atlas_query_window_start_utc"] = day.isoformat()
                    payload["_atlas_query_window_end_utc"] = next_day.isoformat()
                    yield payload
                chunks.append({
                    "symbol": symbol,
                    "query_start_utc": day.isoformat(),
                    "query_end_utc": next_day.isoformat(),
                    "rows": len(ticks),
                    "first_time_msc": first_msc,
                    "last_time_msc": last_msc,
                    "last_error_after_call": list(mt5.last_error()),
                    "completeness": "UNVERIFIED",
                    "boundary_semantics": "POTENTIAL_INCLUSIVE_OVERLAP_UNRESOLVED",
                })
                day = next_day

    count, digest = _write_jsonl_gz(path, rows())
    return count, digest, chunks


def export_with_module(
    mt5: Any,
    *,
    out_dir: Path,
    start: datetime,
    end: datetime,
    symbols: list[str],
    include_ticks: bool,
    account_alias: str,
    history_query_padding_hours: int = 36,
) -> tuple[dict[str, Any], str]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be after start")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    account_alias = str(account_alias).strip()
    if not account_alias:
        raise ValueError("account_alias is required")
    if history_query_padding_hours < 0 or history_query_padding_hours > 168:
        raise ValueError("history_query_padding_hours must be between 0 and 168")
    symbols = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    if not symbols:
        raise ValueError("at least one symbol is required")
    if len(symbols) != len(set(symbols)):
        raise ValueError("symbols must be unique")
    if out_dir.exists():
        raise FileExistsError(f"output already exists: {out_dir}")
    partial_dir = out_dir.with_name(out_dir.name + ".partial")
    if partial_dir.exists():
        raise FileExistsError(f"partial output already exists: {partial_dir}")

    terminal, account = _require_connected(mt5)
    version = mt5.version()
    history_start = start - timedelta(hours=history_query_padding_hours)
    history_end = end + timedelta(hours=history_query_padding_hours)
    tick_query_start = history_start
    tick_query_end = history_end

    deals = mt5.history_deals_get(history_start, history_end)
    if deals is None:
        raise RuntimeError(f"MT5 history_deals_get failed: {mt5.last_error()}")
    orders = mt5.history_orders_get(history_start, history_end)
    if orders is None:
        raise RuntimeError(f"MT5 history_orders_get failed: {mt5.last_error()}")

    terminal_raw = _jsonable_row(terminal)
    account_raw = _jsonable_row(account)
    terminal_payload = {
        key: terminal_raw[key]
        for key in ("connected", "trade_allowed", "build", "maxbars")
        if key in terminal_raw
    }
    account_payload = {
        key: account_raw[key]
        for key in (
            "server",
            "currency",
            "currency_digits",
            "leverage",
            "trade_mode",
            "margin_mode",
            "balance",
            "equity",
            "margin",
            "margin_free",
        )
        if key in account_raw
    }

    symbol_info: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol_info failed for {symbol}: {mt5.last_error()}")
        symbol_info[symbol] = _jsonable_row(info)

    partial_dir.mkdir(parents=True, exist_ok=False)
    deal_count, deal_hash = _write_jsonl_gz(
        partial_dir / "deals.jsonl.gz",
        _indexed_rows(deals, source_kind="DEAL"),
    )
    order_count, order_hash = _write_jsonl_gz(
        partial_dir / "orders.jsonl.gz",
        _indexed_rows(orders, source_kind="ORDER"),
    )

    tick_count = 0
    tick_hash = None
    tick_chunks: list[dict[str, Any]] = []
    if include_ticks:
        tick_count, tick_hash, tick_chunks = _write_ticks_by_day(
            partial_dir / "ticks.jsonl.gz",
            mt5,
            symbols=symbols,
            start=tick_query_start,
            end=tick_query_end,
        )

    manifest = {
        "schema": "atlas-atx00-mt5-raw-export-v1",
        "authority": "RAW_EVIDENCE_ONLY_NO_ORDER",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "account_alias": account_alias,
        "requested_window_start_utc": start.isoformat(),
        "requested_window_end_utc": end.isoformat(),
        "history_query_window_start_utc": history_start.isoformat(),
        "history_query_window_end_utc": history_end.isoformat(),
        "tick_query_window_start_utc": tick_query_start.isoformat(),
        "tick_query_window_end_utc": tick_query_end.isoformat(),
        "history_time_basis": "UNVERIFIED_RAW_MT5_HISTORY_FIELDS",
        "tick_time_basis": "MT5_DOCUMENTED_UTC_UNVERIFIED",
        "history_query_padding_hours": history_query_padding_hours,
        "symbols": symbols,
        "include_ticks": include_ticks,
        "terminal_version": list(version) if version else None,
        "terminal_snapshot_at_export": terminal_payload,
        "account_snapshot_at_export": account_payload,
        "symbol_info_snapshot_at_export": symbol_info,
        "artifacts": {
            "deals.jsonl.gz": {"rows": deal_count, "sha256": deal_hash},
            "orders.jsonl.gz": {"rows": order_count, "sha256": order_hash},
        },
        "normalization_boundaries": {
            "api_index_is_local_export_order_only": True,
            "deal_order_time_mapping_required": True,
            "tick_completeness": "UNVERIFIED",
            "tick_chunk_boundary_semantics": "POTENTIAL_INCLUSIVE_OVERLAP_UNRESOLVED",
        },
    }
    if include_ticks:
        manifest["artifacts"]["ticks.jsonl.gz"] = {
            "rows": tick_count,
            "sha256": tick_hash,
            "chunks": tick_chunks,
        }

    manifest_path = partial_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest_sha256 = _sha256_file(manifest_path)
    (partial_dir / "manifest.sha256").write_text(
        manifest_sha256 + "  manifest.json\n",
        encoding="ascii",
    )
    if out_dir.exists():
        raise FileExistsError(f"output appeared during export: {out_dir}")
    partial_dir.rename(out_dir)
    return manifest, manifest_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--end", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--symbols", required=True, help="comma-separated broker symbols")
    parser.add_argument("--account-alias", required=True, help="non-secret local alias")
    parser.add_argument("--out", required=True)
    parser.add_argument("--terminal-path", default=None)
    parser.add_argument("--include-ticks", action="store_true")
    args = parser.parse_args()

    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "MetaTrader5 Python package is unavailable. Run this on the MT5 Windows host."
        ) from exc

    kwargs: dict[str, Any] = {}
    if args.terminal_path:
        kwargs["path"] = args.terminal_path
    if not mt5.initialize(**kwargs):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        manifest, manifest_sha256 = export_with_module(
            mt5,
            out_dir=Path(args.out),
            start=_parse_utc(args.start),
            end=_parse_utc(args.end),
            symbols=[s.strip() for s in args.symbols.split(",") if s.strip()],
            include_ticks=args.include_ticks,
            account_alias=args.account_alias,
        )
        print(json.dumps(
            {
                "manifest": manifest,
                "manifest_file_sha256": manifest_sha256,
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ))
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
