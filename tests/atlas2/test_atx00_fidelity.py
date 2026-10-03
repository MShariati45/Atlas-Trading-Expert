import json
import tempfile
import unittest
from pathlib import Path

from atlas2.research.atx00 import (
    BarrierBar,
    Fill,
    RiskCommitment,
    RiskWindow,
    StopUpdate,
    concurrent_risk_at,
    effective_stop_at,
    feature_available_at_decision,
    reconcile_account_balance,
    reconcile_fifo_cash,
    register_atx00,
    resolve_barrier_ohlc,
    run_golden_cases,
)
from atlas2.research.registry import ResearchRegistry
from atlas2.store.repository import Store


T0 = 1_700_000_000_000_000


class ATX00FidelityTests(unittest.TestCase):
    def test_same_bar_stop_target_is_ambiguous(self):
        result = resolve_barrier_ohlc(
            direction="LONG",
            stop_price=95,
            target_price=105,
            bar=BarrierBar(T0, T0 + 900_000_000, 100, 106, 94, 101, "BID"),
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.ambiguity, "SAME_BAR_STOP_TARGET_ORDER")
        self.assertIsNone(result.exit_price)

    def test_short_barrier_requires_ask_and_resolves_directionally(self):
        with self.assertRaisesRegex(ValueError, "SHORT exits require ASK OHLC"):
            resolve_barrier_ohlc(
                direction="SHORT",
                stop_price=105,
                target_price=95,
                bar=BarrierBar(
                    T0, T0 + 900_000_000, 100, 106, 94, 99, "BID"
                ),
            )
        result = resolve_barrier_ohlc(
            direction="SHORT",
            stop_price=105,
            target_price=95,
            bar=BarrierBar(
                T0, T0 + 900_000_000, 100, 104, 94, 96, "ASK"
            ),
        )
        self.assertEqual((result.status, result.exit_reason), ("RESOLVED", "TARGET"))
        self.assertEqual(result.exit_price, 95)

    def test_gap_through_target_uses_limit_not_favorable_improvement(self):
        long_result = resolve_barrier_ohlc(
            direction="LONG",
            stop_price=95,
            target_price=105,
            bar=BarrierBar(T0, T0 + 900_000_000, 108, 110, 94, 101, "BID"),
        )
        short_result = resolve_barrier_ohlc(
            direction="SHORT",
            stop_price=105,
            target_price=95,
            bar=BarrierBar(T0, T0 + 900_000_000, 92, 106, 90, 101, "ASK"),
        )
        self.assertEqual(long_result.exit_price, 105)
        self.assertEqual(short_result.exit_price, 95)
        self.assertEqual(long_result.ambiguity, "GAP_THROUGH_TARGET")
        self.assertEqual(short_result.ambiguity, "GAP_THROUGH_TARGET")

    def test_short_gap_through_stop_uses_ask_open(self):
        result = resolve_barrier_ohlc(
            direction="SHORT",
            stop_price=105,
            target_price=95,
            bar=BarrierBar(T0, T0 + 900_000_000, 108, 110, 100, 106, "ASK"),
        )
        self.assertEqual((result.exit_reason, result.exit_price), ("STOP", 108))
        self.assertEqual(result.ambiguity, "GAP_THROUGH_STOP")

    def test_gap_through_stop_uses_first_executable_bar_price(self):
        result = resolve_barrier_ohlc(
            direction="LONG",
            stop_price=95,
            target_price=105,
            bar=BarrierBar(T0, T0 + 900_000_000, 92, 99, 90, 96, "BID"),
        )
        self.assertEqual((result.status, result.exit_reason), ("RESOLVED", "STOP"))
        self.assertEqual(result.exit_price, 92)
        self.assertEqual(result.ambiguity, "GAP_THROUGH_STOP")

    def test_stop_prices_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "initial stop must be positive"):
            effective_stop_at(initial_stop=0, updates=(), as_of_us=T0)
        with self.assertRaisesRegex(ValueError, "requested stop must be positive"):
            effective_stop_at(
                initial_stop=95,
                updates=(StopUpdate(T0 + 1, 0, "ACKED", T0 + 2),),
                as_of_us=T0 + 3,
            )

    def test_stop_request_only_changes_state_after_ack(self):
        ack = StopUpdate(T0 + 10, 100, "ACKED", T0 + 20)
        reject = StopUpdate(T0 + 30, 101, "REJECTED", T0 + 40)
        self.assertEqual(
            effective_stop_at(initial_stop=95, updates=(ack, reject), as_of_us=T0 + 15),
            95,
        )
        self.assertEqual(
            effective_stop_at(initial_stop=95, updates=(ack, reject), as_of_us=T0 + 50),
            100,
        )

    def test_partial_fill_cash_and_costs_reconcile_once(self):
        result = reconcile_fifo_cash(
            direction="LONG",
            entry_fills=(
                Fill(T0 + 1, 2, 100, commission_micro=3),
                Fill(T0 + 2, 1, 101, commission_micro=2),
            ),
            exit_fills=(Fill(T0 + 3, 2, 104, commission_micro=4),),
            cash_per_price_unit_micro=10,
            extra_cost_micro=1,
        )
        self.assertEqual(result.entry_volume_units, 3)
        self.assertEqual(result.exit_volume_units, 2)
        self.assertEqual(result.open_volume_units, 1)
        self.assertEqual(result.gross_cash_micro, 80)
        self.assertEqual(result.explicit_cost_micro, 10)
        self.assertEqual(result.net_cash_micro, 70)

    def test_execution_cash_replay_enforces_position_chronology(self):
        with self.assertRaisesRegex(
            ValueError, "exit exceeds position available at that time"
        ):
            reconcile_fifo_cash(
                direction="LONG",
                entry_fills=(Fill(T0 + 10, 1, 100),),
                exit_fills=(Fill(T0 + 5, 1, 105),),
                cash_per_price_unit_micro=10,
            )
        with self.assertRaisesRegex(
            ValueError, "exit exceeds position available at that time"
        ):
            reconcile_fifo_cash(
                direction="LONG",
                entry_fills=(
                    Fill(T0 + 1, 1, 100),
                    Fill(T0 + 10, 1, 100),
                ),
                exit_fills=(Fill(T0 + 5, 2, 104),),
                cash_per_price_unit_micro=10,
            )

    def test_short_fill_cash_uses_inverse_price_sign(self):
        result = reconcile_fifo_cash(
            direction="SHORT",
            entry_fills=(Fill(T0 + 1, 1, 105),),
            exit_fills=(Fill(T0 + 2, 1, 100),),
            cash_per_price_unit_micro=10,
        )
        self.assertEqual(result.gross_cash_micro, 50)
        self.assertEqual(result.net_cash_micro, 50)

    def test_short_multi_fill_partial_exit_is_fifo_and_costed(self):
        result = reconcile_fifo_cash(
            direction="SHORT",
            entry_fills=(
                Fill(T0 + 1, 1, 105, commission_micro=2),
                Fill(T0 + 2, 2, 104, commission_micro=3),
            ),
            exit_fills=(Fill(T0 + 3, 2, 100, commission_micro=4),),
            cash_per_price_unit_micro=10,
            extra_cost_micro=1,
        )
        self.assertEqual(result.entry_volume_units, 3)
        self.assertEqual(result.exit_volume_units, 2)
        self.assertEqual(result.open_volume_units, 1)
        self.assertEqual(result.gross_cash_micro, 90)
        self.assertEqual(result.explicit_cost_micro, 10)
        self.assertEqual(result.net_cash_micro, 80)

    def test_same_time_execution_events_need_source_sequence(self):
        with self.assertRaisesRegex(ValueError, "same-time fills require unique source_seq"):
            reconcile_fifo_cash(
                direction="LONG",
                entry_fills=(
                    Fill(T0 + 1, 1, 100),
                    Fill(T0 + 1, 1, 101),
                ),
                exit_fills=(Fill(T0 + 2, 1, 102),),
                cash_per_price_unit_micro=10,
            )
        with self.assertRaisesRegex(ValueError, "same-time fills require unique source_seq"):
            reconcile_fifo_cash(
                direction="LONG",
                entry_fills=(Fill(T0 + 1, 1, 100),),
                exit_fills=(Fill(T0 + 1, 1, 101),),
                cash_per_price_unit_micro=10,
            )
        ordered = reconcile_fifo_cash(
            direction="LONG",
            entry_fills=(Fill(T0 + 1, 1, 100, source_seq=1),),
            exit_fills=(Fill(T0 + 1, 1, 101, source_seq=2),),
            cash_per_price_unit_micro=10,
        )
        self.assertEqual(ordered.net_cash_micro, 10)

        with self.assertRaisesRegex(
            ValueError, "same-time stop updates require unique source_seq"
        ):
            effective_stop_at(
                initial_stop=95,
                updates=(
                    StopUpdate(T0 + 1, 98, "ACKED", T0 + 2),
                    StopUpdate(T0 + 1, 99, "ACKED", T0 + 2),
                ),
                as_of_us=T0 + 3,
            )

    def test_explicit_conversion_factor_changes_cash_without_hidden_defaults(self):
        result = reconcile_fifo_cash(
            direction="LONG",
            entry_fills=(Fill(T0 + 1, 1, 100),),
            exit_fills=(Fill(T0 + 2, 1, 102),),
            cash_per_price_unit_micro=12,
        )
        self.assertEqual(result.gross_cash_micro, 24)
        self.assertEqual(result.net_cash_micro, 24)

    def test_risk_day_is_explicit_half_open_window(self):
        window = RiskWindow(T0, T0 + 100)
        self.assertTrue(window.contains(T0))
        self.assertTrue(window.contains(T0 + 99))
        self.assertFalse(window.contains(T0 + 100))

    def test_open_and_pending_risk_are_counted_concurrently(self):
        result = concurrent_risk_at(
            commitments=(
                RiskCommitment("position-a", T0, None, 40),
                RiskCommitment("pending-b", T0 + 1, None, 70),
            ),
            as_of_us=T0 + 2,
            cap_cash_micro=100,
        )
        self.assertEqual(result.total_risk_cash_micro, 110)
        self.assertFalse(result.within_cap)
        self.assertEqual(
            result.active_commitment_ids, ("pending-b", "position-a")
        )

    def test_duplicate_risk_commitment_identity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate risk commitment_id"):
            concurrent_risk_at(
                commitments=(
                    RiskCommitment("same", T0, None, 40),
                    RiskCommitment("same", T0 + 1, None, 50),
                ),
                as_of_us=T0 + 2,
                cap_cash_micro=100,
            )

    def test_account_balance_requires_exact_cash_reconciliation(self):
        good = reconcile_account_balance(
            starting_balance_micro=1_000,
            realized_trade_cash_micro=(100, -30),
            exogenous_cash_micro=(10,),
            observed_ending_balance_micro=1_080,
        )
        bad = reconcile_account_balance(
            starting_balance_micro=1_000,
            realized_trade_cash_micro=(100, -30),
            exogenous_cash_micro=(10,),
            observed_ending_balance_micro=1_079,
        )
        self.assertTrue(good.reconciled)
        self.assertFalse(bad.reconciled)
        self.assertEqual(bad.difference_micro, -1)

    def test_feature_event_time_does_not_override_late_confirmation(self):
        self.assertTrue(
            feature_available_at_decision(
                event_time_us=T0 - 100,
                available_at_us=T0 - 20,
                confirmation_time_us=T0 - 10,
                decision_time_us=T0,
            )
        )
        self.assertFalse(
            feature_available_at_decision(
                event_time_us=T0 - 100,
                available_at_us=T0 - 20,
                confirmation_time_us=T0 + 1,
                decision_time_us=T0,
            )
        )

    def test_feature_time_ordering_must_be_internally_possible(self):
        with self.assertRaisesRegex(
            ValueError, "availability cannot precede event time"
        ):
            feature_available_at_decision(
                event_time_us=T0,
                available_at_us=T0 - 1,
                decision_time_us=T0 + 10,
            )
        with self.assertRaisesRegex(
            ValueError, "confirmation cannot precede event time"
        ):
            feature_available_at_decision(
                event_time_us=T0,
                available_at_us=T0,
                confirmation_time_us=T0 - 1,
                decision_time_us=T0 + 10,
            )

    def test_atx00_maps_to_existing_registry_not_second_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "store")
            self.addCleanup(store.close)
            registry = ResearchRegistry(store)
            exp = register_atx00(
                registry,
                target_commit="774f1b9",
                baseline_policy_version="owner-track-a-2026-10-02",
                registered_by="ali",
                request_key="atx00-fidelity-v1",
            )
            row = store.conn.execute(
                """SELECT e.experiment_type,p.payload_json
                   FROM research_experiments e
                   JOIN research_preregistrations p
                     ON p.prereg_digest=e.prereg_digest
                   WHERE e.experiment_id=?""",
                (exp.experiment_id,),
            ).fetchone()
            stored = json.loads(row["payload_json"])
            self.assertEqual(row["experiment_type"], "ENGINEERING")
            self.assertEqual(stored["registry_experiment_type"], "ENGINEERING")
            self.assertEqual(stored["alias"], "ATX-00")
            self.assertFalse(stored["model_search"])
            self.assertEqual(stored["authority"], "LAB_ONLY_NO_ORDER")

    def test_golden_self_check_passes_without_claiming_atx00_complete(self):
        packet = run_golden_cases()
        self.assertTrue(packet["pass"])
        self.assertEqual(packet["slice"], "ATX00-1")
        self.assertIn(
            "full_chronological_account_replay_integration",
            packet["remaining_atx00_coverage"],
        )


if __name__ == "__main__":
    unittest.main()
