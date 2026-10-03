from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import run_atx00_mt5_evidence_export as exporter


Terminal = namedtuple(
    "Terminal",
    "connected build trade_allowed path data_path commondata_path maxbars",
)
Account = namedtuple(
    "Account",
    "login server currency balance equity leverage name margin margin_free",
)
Symbol = namedtuple("Symbol", "name digits point trade_tick_size trade_tick_value")
Deal = namedtuple(
    "Deal",
    "ticket time_msc symbol type entry volume price commission swap profit",
)
Order = namedtuple(
    "Order",
    "ticket time_setup_msc symbol type volume_initial price_open state",
)


class FakeMT5:
    COPY_TICKS_ALL = 0xFFFF

    def __init__(self):
        self.tick_calls = []
        self.history_calls = []

    def terminal_info(self):
        return Terminal(
            True,
            5000,
            False,
            "C:/Users/Alice/terminal64.exe",
            "C:/Users/Alice/AppData/MetaQuotes",
            "C:/Users/Alice/Common",
            100000,
        )

    def account_info(self):
        return Account(
            12345678,
            "Broker-Demo",
            "USD",
            10000.0,
            10010.0,
            100,
            "Private Person",
            0.0,
            10010.0,
        )

    def version(self):
        return (500, 5000, "01 Jan 2026")

    def history_deals_get(self, start, end):
        self.history_calls.append(("deals", start, end))
        return (
            Deal(11, 1700000000000, "EURUSD", 0, 0, 0.1, 1.1, -1.0, 0.0, 5.0),
            Deal(12, 1700000100000, "EURUSD", 1, 1, 0.1, 1.2, -1.0, -0.5, 10.0),
        )

    def history_orders_get(self, start, end):
        self.history_calls.append(("orders", start, end))
        return (Order(21, 1700000000000, "EURUSD", 0, 0.1, 1.1, 4),)

    def symbol_info(self, symbol):
        return Symbol(symbol, 5, 0.00001, 0.00001, 1.0)

    def copy_ticks_range(self, symbol, start, end, flags):
        self.tick_calls.append((symbol, start, end, flags))
        return [
            {
                "time": 1700000000,
                "time_msc": 1700000000000,
                "bid": 1.1,
                "ask": 1.10002,
                "flags": 6,
            }
        ]

    def last_error(self):
        return (0, "OK")


class ATX00MT5RawExporterTests(unittest.TestCase):
    def _export(self, mt5, out: Path, *, include_ticks=True):
        return exporter.export_with_module(
            mt5,
            out_dir=out,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 2, tzinfo=timezone.utc),
            symbols=["EURUSD"],
            include_ticks=include_ticks,
            account_alias="owner-demo",
        )

    def test_export_is_read_only_source_bound_and_hides_identity_fields(self):
        mt5 = FakeMT5()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evidence"
            manifest, manifest_hash = self._export(mt5, out)
            self.assertEqual(manifest["authority"], "RAW_EVIDENCE_ONLY_NO_ORDER")
            self.assertEqual(manifest["account_alias"], "owner-demo")
            account = manifest["account_snapshot_at_export"]
            terminal = manifest["terminal_snapshot_at_export"]
            self.assertNotIn("login", account)
            self.assertNotIn("name", account)
            self.assertNotIn("path", terminal)
            self.assertNotIn("data_path", terminal)
            self.assertNotIn("commondata_path", terminal)
            self.assertEqual(
                manifest["history_time_basis"],
                "UNVERIFIED_RAW_MT5_HISTORY_FIELDS",
            )
            self.assertEqual(
                manifest["tick_time_basis"],
                "MT5_DOCUMENTED_UTC_UNVERIFIED",
            )
            self.assertEqual(manifest["artifacts"]["deals.jsonl.gz"]["rows"], 2)
            self.assertEqual(manifest["artifacts"]["orders.jsonl.gz"]["rows"], 1)
            self.assertEqual(manifest["artifacts"]["ticks.jsonl.gz"]["rows"], 4)
            self.assertEqual(len(manifest_hash), 64)
            self.assertTrue((out / "manifest.json").exists())
            self.assertTrue((out / "manifest.sha256").exists())
            chunks = manifest["artifacts"]["ticks.jsonl.gz"]["chunks"]
            self.assertEqual(chunks[0]["completeness"], "UNVERIFIED")
            self.assertEqual(
                chunks[0]["boundary_semantics"],
                "POTENTIAL_INCLUSIVE_OVERLAP_UNRESOLVED",
            )

            with gzip.open(out / "deals.jsonl.gz", "rt", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
            self.assertEqual([row["ticket"] for row in rows], [11, 12])
            self.assertEqual([row["_atlas_api_index"] for row in rows], [0, 1])
            self.assertEqual(len(mt5.tick_calls), 4)
            self.assertLess(
                mt5.tick_calls[0][1],
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            self.assertGreater(
                mt5.tick_calls[-1][2],
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            )

    def test_history_query_is_padded_but_requested_window_stays_explicit(self):
        mt5 = FakeMT5()
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _ = self._export(mt5, Path(tmp) / "evidence", include_ticks=False)
            self.assertEqual(
                manifest["requested_window_start_utc"],
                "2026-01-01T00:00:00+00:00",
            )
            self.assertEqual(manifest["history_query_padding_hours"], 36)
            deals_call = next(call for call in mt5.history_calls if call[0] == "deals")
            self.assertLess(deals_call[1], datetime(2026, 1, 1, tzinfo=timezone.utc))
            self.assertGreater(deals_call[2], datetime(2026, 1, 2, tzinfo=timezone.utc))

    def test_gzip_artifact_hashes_are_deterministic_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m1, _ = self._export(FakeMT5(), root / "one", include_ticks=True)
            m2, _ = self._export(FakeMT5(), root / "two", include_ticks=True)
            self.assertEqual(
                m1["artifacts"]["deals.jsonl.gz"]["sha256"],
                m2["artifacts"]["deals.jsonl.gz"]["sha256"],
            )
            self.assertEqual(
                m1["artifacts"]["orders.jsonl.gz"]["sha256"],
                m2["artifacts"]["orders.jsonl.gz"]["sha256"],
            )
            self.assertEqual(
                m1["artifacts"]["ticks.jsonl.gz"]["sha256"],
                m2["artifacts"]["ticks.jsonl.gz"]["sha256"],
            )

    def test_requires_connected_terminal(self):
        mt5 = FakeMT5()
        mt5.terminal_info = lambda: Terminal(
            False, 5000, False, "x", "y", "z", 100000
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "not connected"):
                self._export(mt5, Path(tmp) / "evidence", include_ticks=False)

    def test_timezone_alias_and_window_are_explicit(self):
        mt5 = FakeMT5()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                exporter.export_with_module(
                    mt5,
                    out_dir=Path(tmp) / "evidence",
                    start=datetime(2026, 1, 1),
                    end=datetime(2026, 1, 2),
                    symbols=["EURUSD"],
                    include_ticks=False,
                    account_alias="owner-demo",
                )
            with self.assertRaisesRegex(ValueError, "account_alias"):
                exporter.export_with_module(
                    mt5,
                    out_dir=Path(tmp) / "evidence-2",
                    start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    symbols=["EURUSD"],
                    include_ticks=False,
                    account_alias="",
                )
        with self.assertRaisesRegex(ValueError, "timezone"):
            exporter._parse_utc("2026-01-01T00:00:00")

    def test_existing_output_and_partial_output_are_refused(self):
        mt5 = FakeMT5()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "evidence"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                self._export(mt5, out, include_ticks=False)
            out.rmdir()
            (root / "evidence.partial").mkdir()
            with self.assertRaises(FileExistsError):
                self._export(mt5, out, include_ticks=False)

    def test_nan_metadata_fails_closed_and_leaves_partial(self):
        mt5 = FakeMT5()
        mt5.symbol_info = lambda symbol: Symbol(
            symbol, 5, float("nan"), 0.00001, 1.0
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "evidence"
            with self.assertRaises(ValueError):
                self._export(mt5, out, include_ticks=False)
            self.assertFalse(out.exists())
            self.assertTrue((root / "evidence.partial").exists())

    def test_mid_export_failure_leaves_only_partial_directory(self):
        mt5 = FakeMT5()
        mt5.copy_ticks_range = lambda *args, **kwargs: None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "evidence"
            with self.assertRaisesRegex(RuntimeError, "copy_ticks_range failed"):
                self._export(mt5, out, include_ticks=True)
            self.assertFalse(out.exists())
            self.assertTrue((root / "evidence.partial").exists())


if __name__ == "__main__":
    unittest.main()
