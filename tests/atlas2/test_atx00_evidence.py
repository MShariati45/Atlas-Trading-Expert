import tempfile
import unittest
from pathlib import Path

from atlas2.core.enums import AvailabilityBasis
from atlas2.core.ids import make_id
from atlas2.data.datasets import freeze_dataset
from atlas2.data.ingest import ingest_source_bytes
from atlas2.data.normalize_mt5 import normalize_quote
from atlas2.research.atx00_evidence import (
    ExecutionEvidenceBundle,
    ExecutionEvidenceEvent,
    bind_execution_events,
    bind_quote_evidence,
    replay_account_evidence,
)
from atlas2.store.repository import Store


T0 = 1_700_000_000_000_000
CLOCK = make_id("comp", "clock-profile-v1", {"zone": "UTC"})
OTHER_CLOCK = make_id("comp", "clock-profile-v1", {"zone": "SERVER"})
SPEC = make_id("comp", "instrument-spec-v1", {"symbol": "EURUSD", "digits": 5})
NORM = make_id("comp", "normalizer-v1", {"name": "mt5"})
SOURCE_HASH = "a" * 64


class ATX00EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "store")
        self.addCleanup(self.store.close)

    def _dataset_with_quotes(self, *, clock=CLOCK, quote_clock=CLOCK, missing_seq=False):
        obs = ingest_source_bytes(
            self.store,
            b"quotes",
            source_id="fixture-export",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=T0 + 100,
            clock_profile_id=quote_clock,
        )
        rows = []
        for index, (bid, ask) in enumerate(((100000, 100002), (100001, 100003))):
            fact, link = normalize_quote(
                {
                    "time_us": T0 + index,
                    "source_seq": None if missing_seq and index == 1 else index,
                    "bid": f"{bid / 100000:.5f}",
                    "ask": f"{ask / 100000:.5f}",
                },
                obs,
                locator=f"row:{index}",
                normalizer_version_id=NORM,
                instrument_id="EURUSD",
                price_digits=5,
                instrument_spec_id=SPEC,
                availability_basis=AvailabilityBasis.SOURCE_STAMPED,
                available_at_us=T0 + index,
            )
            self.store.put_many([fact, link])
            rows.append(("QUOTE", fact.fact_id, link.obs_id, link.locator))
        ds = freeze_dataset(
            self.store,
            rows,
            coverage={"instruments": ["EURUSD"], "start_us": T0, "end_us": T0 + 2},
            causal_policy={"quote": "source_published"},
            htf_policy={"base": "M15", "alignment": "DECLARED"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=clock,
            instrument_specs={"EURUSD": SPEC},
            tzdata_version="fixture-v1",
            display_name="atx00 quotes",
            built_at_us=T0 + 200,
        )
        return ds

    def test_quote_evidence_binds_sealed_causal_source_sequence(self):
        ds = self._dataset_with_quotes()
        bound = bind_quote_evidence(
            self.store,
            dataset_id=ds.dataset_id,
            instrument_id="EURUSD",
            start_us=T0,
            end_us=T0 + 2,
            as_of_us=T0 + 2,
        )
        self.assertEqual(len(bound.quotes), 2)
        self.assertEqual([q.source_seq for q in bound.quotes], [0, 1])
        self.assertEqual(bound.clock_profile_id, CLOCK)
        self.assertEqual(len(bound.quote_digest), 64)

    def test_quote_evidence_rejects_missing_sequence_and_clock_mismatch(self):
        ds = self._dataset_with_quotes(missing_seq=True)
        with self.assertRaisesRegex(ValueError, "requires source_seq"):
            bind_quote_evidence(
                self.store,
                dataset_id=ds.dataset_id,
                instrument_id="EURUSD",
                start_us=T0,
                end_us=T0 + 2,
                as_of_us=T0 + 2,
            )

        with tempfile.TemporaryDirectory() as tmp:
            other = Store(Path(tmp) / "store")
            self.addCleanup(other.close)
            original = self.store
            self.store = other
            try:
                bad = self._dataset_with_quotes(clock=CLOCK, quote_clock=OTHER_CLOCK)
                with self.assertRaisesRegex(ValueError, "clock profile mismatch"):
                    bind_quote_evidence(
                        other,
                        dataset_id=bad.dataset_id,
                        instrument_id="EURUSD",
                        start_us=T0,
                        end_us=T0 + 2,
                        as_of_us=T0 + 2,
                    )
            finally:
                self.store = original
    def _event(self, event_id, kind, time_offset, seq, **kwargs):
        return ExecutionEvidenceEvent(
            event_id=event_id,
            source_sha256=SOURCE_HASH,
            locator=f"line:{seq}",
            event_kind=kind,
            time_us=T0 + time_offset,
            source_seq=seq,
            **kwargs,
        )

    def test_execution_bundle_is_source_bound_and_deterministic(self):
        events = (
            self._event(
                "e2", "EXIT_FILL", 20, 2,
                trade_id="t1", direction="LONG", volume_units=1, price=105,
                cash_per_price_unit_micro=10, commission_cost_micro=2,
            ),
            self._event(
                "e1", "ENTRY_FILL", 10, 1,
                trade_id="t1", direction="LONG", volume_units=1, price=100,
                commission_cost_micro=1,
            ),
        )
        bound = bind_execution_events(events)
        reverse = bind_execution_events(tuple(reversed(events)))
        self.assertEqual(bound.bundle_digest, reverse.bundle_digest)
        self.assertEqual([e.event_id for e in bound.events], ["e1", "e2"])

    def test_account_replay_cash_risk_and_stop_ack(self):
        events = (
            self._event("r1", "RISK_START", 1, 1, commitment_id="c1", risk_cash_micro=60),
            self._event("r2", "RISK_START", 2, 2, commitment_id="c2", risk_cash_micro=50),
            self._event(
                "f1", "ENTRY_FILL", 3, 3,
                trade_id="t1", direction="LONG", volume_units=2, price=100,
                commission_cost_micro=2,
            ),
            self._event(
                "s1", "STOP_REQUEST", 4, 4,
                trade_id="t1", request_id="req1", stop_price=98,
            ),
            self._event("s2", "STOP_ACK", 5, 5, trade_id="t1", request_id="req1"),
            self._event("r3", "RISK_END", 6, 6, commitment_id="c2"),
            self._event(
                "f2", "EXIT_FILL", 7, 7,
                trade_id="t1", direction="LONG", volume_units=1, price=105,
                cash_per_price_unit_micro=10, commission_cost_micro=3,
            ),
            self._event("cash", "CASH_ADJUSTMENT", 8, 8, cash_delta_micro=20),
        )
        bundle = bind_execution_events(events)
        result = replay_account_evidence(
            bundle,
            starting_balance_micro=1_000,
            risk_cap_cash_micro=100,
        )
        self.assertEqual(result.realized_gross_micro, 50)
        self.assertEqual(result.incurred_cost_micro, 5)
        self.assertEqual(result.exogenous_cash_micro, 20)
        self.assertEqual(result.ending_balance_micro, 1_065)
        self.assertEqual(result.open_volume_by_trade_json, '{"t1":1}')
        self.assertEqual(result.active_risk_cash_micro, 60)
        self.assertEqual(result.peak_risk_cash_micro, 110)
        self.assertEqual(result.risk_cap_violations, 1)
        self.assertEqual(result.unresolved_stop_request_ids_json, "[]")
        self.assertEqual(result.active_stops_json, '{"t1":98}')
        self.assertEqual(len(result.replay_digest), 64)

    def test_execution_bundle_rejects_duplicate_locator_or_sequence_conflict(self):
        first = self._event(
            "a", "CASH_ADJUSTMENT", 1, 1, cash_delta_micro=1
        )
        duplicate_locator = ExecutionEvidenceEvent(
            event_id="b",
            source_sha256=SOURCE_HASH,
            locator=first.locator,
            event_kind="CASH_ADJUSTMENT",
            time_us=T0 + 2,
            source_seq=2,
            cash_delta_micro=1,
        )
        with self.assertRaisesRegex(ValueError, "source locator"):
            bind_execution_events((first, duplicate_locator))

        later_lower_seq = ExecutionEvidenceEvent(
            event_id="c",
            source_sha256=SOURCE_HASH,
            locator="line:0",
            event_kind="CASH_ADJUSTMENT",
            time_us=T0 + 2,
            source_seq=0,
            cash_delta_micro=1,
        )
        with self.assertRaisesRegex(ValueError, "timestamp conflicts"):
            bind_execution_events((first, later_lower_seq))

    def test_stop_and_risk_id_lifecycle_fail_closed(self):
        events = (
            self._event(
                "f1", "ENTRY_FILL", 1, 1,
                trade_id="t1", direction="LONG", volume_units=1, price=100,
            ),
            self._event(
                "s1", "STOP_REQUEST", 2, 2,
                trade_id="t1", request_id="req", stop_price=98,
            ),
            self._event("s2", "STOP_ACK", 3, 3, trade_id="t1", request_id="req"),
            self._event(
                "f2", "EXIT_FILL", 4, 4,
                trade_id="t1", direction="LONG", volume_units=1, price=101,
                cash_per_price_unit_micro=10,
            ),
        )
        result = replay_account_evidence(
            bind_execution_events(events),
            starting_balance_micro=1_000,
            risk_cap_cash_micro=100,
        )
        self.assertEqual(result.active_stops_json, "{}")

        reused_request = events + (
            self._event(
                "s3", "STOP_REQUEST", 5, 5,
                trade_id="t1", request_id="req", stop_price=99,
            ),
        )
        with self.assertRaisesRegex(ValueError, "requires open trade"):
            replay_account_evidence(
                bind_execution_events(reused_request),
                starting_balance_micro=1_000,
                risk_cap_cash_micro=100,
            )

        reused_risk = (
            self._event("r1", "RISK_START", 1, 1, commitment_id="c", risk_cash_micro=10),
            self._event("r2", "RISK_END", 2, 2, commitment_id="c"),
            self._event("r3", "RISK_START", 3, 3, commitment_id="c", risk_cash_micro=10),
        )
        with self.assertRaisesRegex(ValueError, "commitment_id reused"):
            replay_account_evidence(
                bind_execution_events(reused_risk),
                starting_balance_micro=1_000,
                risk_cap_cash_micro=100,
            )

    def test_execution_contract_rejects_noncanonical_hash_and_entry_conversion(self):
        bad_hash = ExecutionEvidenceEvent(
            event_id="bad-hash",
            source_sha256="A" * 64,
            locator="line:1",
            event_kind="CASH_ADJUSTMENT",
            time_us=T0 + 1,
            source_seq=1,
            cash_delta_micro=1,
        )
        with self.assertRaisesRegex(ValueError, "lowercase sha256"):
            bind_execution_events((bad_hash,))

        bad_entry = self._event(
            "bad-entry", "ENTRY_FILL", 1, 1,
            trade_id="t1", direction="LONG", volume_units=1, price=100,
            cash_per_price_unit_micro=10,
        )
        with self.assertRaisesRegex(ValueError, "must not carry exit conversion"):
            bind_execution_events((bad_entry,))

    def test_replay_rejects_unbound_bundle_and_trade_id_reuse(self):
        event = self._event(
            "cash", "CASH_ADJUSTMENT", 1, 1, cash_delta_micro=1
        )
        forged = ExecutionEvidenceBundle(
            SOURCE_HASH,
            "0" * 64,
            (event,),
        )
        with self.assertRaisesRegex(ValueError, "not canonically bound"):
            replay_account_evidence(
                forged,
                starting_balance_micro=1_000,
                risk_cap_cash_micro=100,
            )

        reused_trade = (
            self._event(
                "f1", "ENTRY_FILL", 1, 1,
                trade_id="t1", direction="LONG", volume_units=1, price=100,
            ),
            self._event(
                "f2", "EXIT_FILL", 2, 2,
                trade_id="t1", direction="LONG", volume_units=1, price=101,
                cash_per_price_unit_micro=10,
            ),
            self._event(
                "f3", "ENTRY_FILL", 3, 3,
                trade_id="t1", direction="LONG", volume_units=1, price=102,
            ),
        )
        with self.assertRaisesRegex(ValueError, "trade_id reused after close"):
            replay_account_evidence(
                bind_execution_events(reused_trade),
                starting_balance_micro=1_000,
                risk_cap_cash_micro=100,
            )

    def test_request_id_reuse_fails_while_trade_remains_open(self):
        events = (
            self._event(
                "f1", "ENTRY_FILL", 1, 1,
                trade_id="t1", direction="LONG", volume_units=2, price=100,
            ),
            self._event(
                "s1", "STOP_REQUEST", 2, 2,
                trade_id="t1", request_id="req", stop_price=98,
            ),
            self._event("s2", "STOP_ACK", 3, 3, trade_id="t1", request_id="req"),
            self._event(
                "s3", "STOP_REQUEST", 4, 4,
                trade_id="t1", request_id="req", stop_price=99,
            ),
        )
        with self.assertRaisesRegex(ValueError, "request_id reused"):
            replay_account_evidence(
                bind_execution_events(events),
                starting_balance_micro=1_000,
                risk_cap_cash_micro=100,
            )

    def test_intermediate_cash_overflow_fails_even_if_later_event_would_reverse_it(self):
        max_i64 = 2**63 - 1
        events = (
            self._event("c1", "CASH_ADJUSTMENT", 1, 1, cash_delta_micro=1),
            self._event("c2", "CASH_ADJUSTMENT", 2, 2, cash_delta_micro=-1),
        )
        with self.assertRaises((TypeError, ValueError, OverflowError)):
            replay_account_evidence(
                bind_execution_events(events),
                starting_balance_micro=max_i64,
                risk_cap_cash_micro=0,
            )

    def test_open_volume_intermediate_stays_int64(self):
        max_i64 = 2**63 - 1
        events = (
            self._event(
                "f1", "ENTRY_FILL", 1, 1,
                trade_id="t1", direction="LONG",
                volume_units=max_i64, price=100,
            ),
            self._event(
                "f2", "ENTRY_FILL", 2, 2,
                trade_id="t1", direction="LONG",
                volume_units=1, price=100,
            ),
        )
        with self.assertRaises((TypeError, ValueError, OverflowError)):
            replay_account_evidence(
                bind_execution_events(events),
                starting_balance_micro=1_000,
                risk_cap_cash_micro=0,
            )

    def test_account_replay_fails_closed_on_bad_chronology_and_source_identity(self):
        exit_only = bind_execution_events((
            self._event(
                "x1", "EXIT_FILL", 1, 1,
                trade_id="t1", direction="LONG", volume_units=1, price=105,
                cash_per_price_unit_micro=10,
            ),
        ))
        with self.assertRaisesRegex(ValueError, "no matching open trade"):
            replay_account_evidence(
                exit_only,
                starting_balance_micro=1_000,
                risk_cap_cash_micro=100,
            )

        other_source = ExecutionEvidenceEvent(
            event_id="bad",
            source_sha256="b" * 64,
            locator="line:2",
            event_kind="CASH_ADJUSTMENT",
            time_us=T0 + 2,
            source_seq=2,
            cash_delta_micro=1,
        )
        with self.assertRaisesRegex(ValueError, "one source blob"):
            bind_execution_events((
                self._event("a", "CASH_ADJUSTMENT", 1, 1, cash_delta_micro=1),
                other_source,
            ))


if __name__ == "__main__":
    unittest.main()
