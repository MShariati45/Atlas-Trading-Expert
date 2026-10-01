import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from atlas2.core.enums import AvailabilityBasis, DataQualityFlag, RunMode, ViewClass
from atlas2.core.errors import HoldoutLocked
from atlas2.core.ids import make_id
from atlas2.core.taint import Taint
from atlas2.data.datasets import (
    freeze_dataset,
    make_bar_fact,
    make_calendar_schedule,
    make_calendar_value,
    make_quote_fact,
)
from atlas2.data.htf import derive_htf
from atlas2.data.ingest import ingest_source_bytes
from atlas2.data.normalize_calendar import normalize_schedule, normalize_value
from atlas2.data.normalize_mt5 import normalize_bar, normalize_quote
from atlas2.data.views import MarketView, OutcomeView
from atlas2.model.data import FactLink
from atlas2.research.registry import ResearchRegistry
from atlas2.store.backup import verify
from atlas2.store.repository import Store, StoreConflict, ConflictKind

M15 = 15 * 60 * 1_000_000
H4 = 4 * 60 * 60 * 1_000_000
COMP = make_id("comp", "test-component-v1", {"name": "normalizer"})
CLOCK = make_id("comp", "clock-profile-v1", {"zone": "UTC"})
SPEC = make_id("comp", "instrument-spec-v1", {"symbol": "EURUSD", "digits": 5})


class DataSpineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "store")
        self.addCleanup(self.store.close)
        self.obs1 = ingest_source_bytes(
            self.store,
            b"source-one",
            source_id="synthetic",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=0,
            clock_profile_id=CLOCK,
        )

    def second_observation(self, acquired_at_us=M15 * 10):
        return ingest_source_bytes(
            self.store,
            b"source-two",
            source_id="synthetic",
            source_version="v1",
            acquisition_kind="HISTORICAL_EXPORT",
            acquired_at_us=acquired_at_us,
            clock_profile_id=CLOCK,
        )

    def put_fact_link(
        self,
        fact,
        *,
        locator,
        available_at_us,
        basis=AvailabilityBasis.BAR_CLOSE_RULE,
        observation=None,
        quality_flags=0,
    ):
        observation = observation or self.obs1
        link = FactLink(
            fact.fact_id,
            observation.obs_id,
            locator,
            COMP,
            available_at_us,
            basis,
            quality_flags,
        )
        self.store.put_many([fact, link])
        return link

    def dataset(self, rows, display_name="synthetic", built_at_us=H4 * 4):
        return freeze_dataset(
            self.store,
            rows,
            coverage={"instruments": ["EURUSD"], "start_us": 0, "end_us": H4 * 2},
            causal_policy={"bar_publication_lag_us": 0},
            htf_policy={"base": "M15", "alignment": "UTC"},
            precedence_policy={"rule": "latest_available_then_fact_id"},
            clock_profile_id=CLOCK,
            instrument_specs={"EURUSD": SPEC},
            tzdata_version="synthetic-v1",
            display_name=display_name,
            built_at_us=built_at_us,
        )

    @staticmethod
    def member(kind, fact, link):
        return (kind, fact.fact_id, link.obs_id, link.locator)

    def bar(self, index=0, *, close=105, high=110):
        return make_bar_fact(
            instrument_id="EURUSD",
            timeframe="M15",
            price_side="BID",
            open_time_us=index * M15,
            close_time_us=(index + 1) * M15,
            open=100 + index,
            high=high + index,
            low=90 + index,
            close=close + index,
            tick_volume=10,
            real_volume=None,
            spread_points=2,
            spread_semantics="LAST",
            instrument_spec_id=SPEC,
        )

    def test_overlapping_observations_one_fact_and_revision_precedence(self):
        original = self.bar()
        l1 = self.put_fact_link(original, locator="row:1", available_at_us=M15)
        obs2 = self.second_observation()
        l2 = self.put_fact_link(
            original,
            locator="row:9",
            available_at_us=M15 * 3,
            observation=obs2,
        )

        revision = self.bar(close=108, high=112)
        l3 = self.put_fact_link(revision, locator="row:2", available_at_us=M15 * 2)

        ds = self.dataset(
            [
                self.member("BAR", original, l1),
                self.member("BAR", original, l2),
                self.member("BAR", revision, l3),
            ]
        )
        view = MarketView(self.store, ds.dataset_id)
        early = view.bars("EURUSD", "M15", "BID", 0, M15, M15)
        late = view.bars("EURUSD", "M15", "BID", 0, M15, M15 * 2)
        self.assertEqual([x.fact.fact_id for x in early], [original.fact_id])
        self.assertEqual(early[0].available_at_us, M15)
        self.assertEqual([x.fact.fact_id for x in late], [revision.fact_id])

    def test_forward_mode_uses_actual_acquisition_time(self):
        obs = self.second_observation(acquired_at_us=M15 * 5)
        bar = self.bar()
        link = self.put_fact_link(
            bar,
            locator="late-observation",
            available_at_us=M15,
            observation=obs,
        )
        ds = self.dataset([self.member("BAR", bar, link)])
        replay = MarketView(self.store, ds.dataset_id, mode=RunMode.REPLAY)
        forward = MarketView(self.store, ds.dataset_id, mode=RunMode.FORWARD)
        self.assertEqual(len(replay.bars("EURUSD", "M15", "BID", 0, M15, M15)), 1)
        self.assertEqual(forward.bars("EURUSD", "M15", "BID", 0, M15, M15), [])
        later = forward.bars("EURUSD", "M15", "BID", 0, M15, M15 * 5)
        self.assertEqual(later[0].available_at_us, M15 * 5)

    def test_unknown_calendar_is_non_pit_only_and_tainted(self):
        schedule = make_calendar_schedule(
            provider_event_key="ev1",
            currency="USD",
            title="CPI",
            impact="HIGH",
            scheduled_time_us=M15 * 3,
            all_day=False,
            reference_period="2026-09",
        )
        value = make_calendar_value(
            provider_event_key="ev1",
            value_kind="ACTUAL",
            value_text="3.1",
            unit="%",
        )
        ls = self.put_fact_link(
            schedule,
            locator="schedule",
            available_at_us=None,
            basis=AvailabilityBasis.UNKNOWN,
        )
        lv = self.put_fact_link(
            value,
            locator="value",
            available_at_us=None,
            basis=AvailabilityBasis.UNKNOWN,
        )
        ds = self.dataset(
            [
                self.member("CALENDAR_SCHEDULE", schedule, ls),
                self.member("CALENDAR_VALUE", value, lv),
            ]
        )
        view = MarketView(self.store, ds.dataset_id)
        self.assertEqual(
            view.calendar_schedules(M15 * 2, M15 * 4, M15 * 10, view_class=ViewClass.PIT),
            [],
        )
        nonpit = view.calendar_schedules(
            M15 * 2, M15 * 4, M15 * 10, view_class=ViewClass.NON_PIT
        )
        self.assertEqual(len(nonpit), 1)
        self.assertTrue(nonpit[0].taint & int(Taint.NON_PIT_MACRO))
        values = view.calendar_values(("ev1",), M15 * 2, M15 * 4, M15 * 10, view_class=ViewClass.NON_PIT)
        self.assertEqual(len(values), 1)
        self.assertTrue(values[0].taint & int(Taint.NON_PIT_MACRO))

    def test_calendar_value_text_is_canonical_decimal(self):
        value = make_calendar_value(
            provider_event_key="ev-decimal",
            value_kind="ACTUAL",
            value_text="3.10",
            unit="%",
        )
        self.assertEqual(value.value_text, "3.1")
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, "canonical decimal"):
            replace(value, value_text="3.10").validate()

    def test_calendar_normalizer_never_invents_availability(self):
        schedule_row = {
            "provider_event_key": "ev2",
            "currency": "USD",
            "title": "NFP",
            "impact": "HIGH",
            "scheduled_time_us": M15 * 4,
            "all_day": False,
        }
        fact, unknown = normalize_schedule(
            schedule_row,
            self.obs1,
            locator="c1",
            normalizer_version_id=COMP,
            availability_basis=AvailabilityBasis.UNKNOWN,
        )
        self.assertIsNone(unknown.available_at_us)
        with self.assertRaises(ValueError):
            normalize_schedule(
                schedule_row,
                self.obs1,
                locator="c2",
                normalizer_version_id=COMP,
                availability_basis=AvailabilityBasis.UNKNOWN,
                available_at_us=M15 * 3,
            )
        observed_fact, observed = normalize_schedule(
            schedule_row,
            self.obs1,
            locator="c3",
            normalizer_version_id=COMP,
            availability_basis=AvailabilityBasis.OBSERVED_BY_ATLAS,
        )
        self.assertEqual(observed.available_at_us, self.obs1.acquired_at_us)
        self.assertEqual(fact.fact_id, observed_fact.fact_id)

    def test_mt5_bar_normalizer_uses_integer_price_and_declared_lag(self):
        fact, link = normalize_bar(
            {
                "open_time_us": 0,
                "close_time_us": M15,
                "open": "1.10000",
                "high": "1.10100",
                "low": "1.09900",
                "close": "1.10050",
                "tick_volume": 10,
                "spread_points": 12,
                "spread_semantics": "LAST",
            },
            self.obs1,
            locator="mt5:1",
            normalizer_version_id=COMP,
            instrument_id="EURUSD",
            timeframe="M15",
            price_side="BID",
            price_digits=5,
            instrument_spec_id=SPEC,
            publication_lag_us=250_000,
        )
        self.assertEqual(fact.open, 110000)
        self.assertEqual(fact.close, 110050)
        self.assertEqual(link.available_at_us, M15 + 250_000)
        self.assertEqual(link.availability_basis, AvailabilityBasis.BAR_CLOSE_RULE)

    def test_quote_normalizer_marks_unknown_multiplicity_and_forward_observation_time(self):
        obs = self.second_observation(acquired_at_us=M15 * 5)
        fact, link = normalize_quote(
            {
                "time_us": M15,
                "bid": "1.10000",
                "ask": "1.10020",
                "source_seq": None,
            },
            obs,
            locator="quote:1",
            normalizer_version_id=COMP,
            instrument_id="EURUSD",
            price_digits=5,
            instrument_spec_id=SPEC,
            availability_basis=AvailabilityBasis.OBSERVED_BY_ATLAS,
            available_at_us=None,
        )
        self.assertIsNone(fact.source_seq)
        self.assertEqual(link.available_at_us, obs.acquired_at_us)
        self.assertTrue(
            link.quality_flags & int(DataQualityFlag.MULTIPLICITY_UNKNOWABLE)
        )
        with self.assertRaises(ValueError):
            normalize_quote(
                {"time_us": M15, "bid": "1.1", "ask": "1.2"},
                obs,
                locator="quote:2",
                normalizer_version_id=COMP,
                instrument_id="EURUSD",
                price_digits=5,
                instrument_spec_id=SPEC,
                availability_basis=AvailabilityBasis.OBSERVED_BY_ATLAS,
                available_at_us=obs.acquired_at_us - 1,
            )

    def test_h4_derives_from_visible_m15_and_ignores_source_h4(self):
        rows = []
        for i in range(16):
            fact = self.bar(i)
            available = (i + 1) * M15 if i != 7 else H4 + M15
            link = self.put_fact_link(
                fact, locator=f"m15:{i}", available_at_us=available
            )
            rows.append(self.member("BAR", fact, link))

        source_h4 = make_bar_fact(
            instrument_id="EURUSD",
            timeframe="H4",
            price_side="BID",
            open_time_us=0,
            close_time_us=H4,
            open=1,
            high=999,
            low=1,
            close=999,
            tick_volume=1,
            real_volume=None,
            spread_points=1,
            spread_semantics="LAST",
            instrument_spec_id=SPEC,
        )
        h4_link = self.put_fact_link(
            source_h4, locator="source-h4", available_at_us=H4
        )
        rows.append(self.member("BAR", source_h4, h4_link))

        ds = self.dataset(rows)
        view = MarketView(self.store, ds.dataset_id)
        incomplete = derive_htf(view, "EURUSD", "H4", "BID", 0, H4)
        self.assertEqual(incomplete.completeness, "INCOMPLETE_MISSING_INPUT")
        self.assertEqual(incomplete.present_constituents, 15)
        self.assertNotEqual(incomplete.high, 999)

        complete = derive_htf(view, "EURUSD", "H4", "BID", 0, H4 + M15)
        self.assertEqual(complete.completeness, "COMPLETE")
        self.assertEqual(complete.present_constituents, 16)
        self.assertEqual(complete.available_at_us, H4 + M15)
        self.assertNotEqual(complete.high, 999)

    def test_partial_h4_uses_only_closed_visible_m15(self):
        rows = []
        for i in range(16):
            fact = self.bar(i)
            link = self.put_fact_link(
                fact, locator=f"partial:{i}", available_at_us=(i + 1) * M15
            )
            rows.append(self.member("BAR", fact, link))
        ds = self.dataset(rows)
        partial = derive_htf(
            MarketView(self.store, ds.dataset_id),
            "EURUSD",
            "H4",
            "BID",
            0,
            M15 * 5,
        )
        self.assertEqual(partial.completeness, "PARTIAL_FORMING")
        self.assertEqual(partial.present_constituents, 5)
        self.assertEqual(partial.available_at_us, M15 * 5)

    def test_missing_constituent_remains_incomplete_after_close(self):
        rows = []
        for i in range(16):
            if i == 4:
                continue
            fact = self.bar(i)
            link = self.put_fact_link(
                fact, locator=f"m15:{i}", available_at_us=(i + 1) * M15
            )
            rows.append(self.member("BAR", fact, link))
        ds = self.dataset(rows)
        derived = derive_htf(
            MarketView(self.store, ds.dataset_id), "EURUSD", "H4", "BID", 0, H4
        )
        self.assertEqual(derived.completeness, "INCOMPLETE_MISSING_INPUT")
        self.assertEqual(derived.present_constituents, 15)

    def test_dataset_identity_ignores_member_order_and_metadata(self):
        a = self.bar(0)
        b = self.bar(1)
        la = self.put_fact_link(a, locator="a", available_at_us=M15)
        lb = self.put_fact_link(b, locator="b", available_at_us=M15 * 2)
        rows = [self.member("BAR", a, la), self.member("BAR", b, lb)]
        first = self.dataset(rows, display_name="first", built_at_us=H4 * 4)
        second = self.dataset(
            list(reversed(rows)), display_name="renamed", built_at_us=H4 * 5
        )
        self.assertEqual(first.dataset_id, second.dataset_id)
        self.assertEqual(first.membership_digest, second.membership_digest)
        self.assertEqual(second.display_name, "first")
        self.assertEqual(second.built_at_us, H4 * 4)

    def test_dataset_membership_is_sealed_after_freeze(self):
        first = self.bar(0)
        first_link = self.put_fact_link(
            first, locator="sealed:0", available_at_us=M15
        )
        ds = self.dataset([self.member("BAR", first, first_link)])

        second = self.bar(1)
        second_link = self.put_fact_link(
            second, locator="sealed:1", available_at_us=M15 * 2
        )
        from atlas2.model.data import DatasetMembership
        extra = DatasetMembership(
            ds.dataset_id,
            "BAR",
            second.fact_id,
            second_link.obs_id,
            second_link.locator,
        )
        with self.assertRaises(StoreConflict) as ctx:
            self.store.put(extra)
        self.assertEqual(ctx.exception.kind, ConflictKind.SEAL_VIOLATION)

    def test_quotes_without_source_sequence_preserve_multiplicity(self):
        q1 = make_quote_fact(
            instrument_id="EURUSD",
            time_us=M15,
            source_seq=None,
            bid=100,
            ask=102,
            bid_volume=None,
            ask_volume=None,
            instrument_spec_id=SPEC,
        )
        q2 = make_quote_fact(
            instrument_id="EURUSD",
            time_us=M15,
            source_seq=None,
            bid=101,
            ask=103,
            bid_volume=None,
            ask_volume=None,
            instrument_spec_id=SPEC,
        )
        l1 = self.put_fact_link(q1, locator="q1", available_at_us=M15)
        l2 = self.put_fact_link(q2, locator="q2", available_at_us=M15)
        ds = self.dataset(
            [self.member("QUOTE", q1, l1), self.member("QUOTE", q2, l2)]
        )
        quotes = MarketView(self.store, ds.dataset_id).quotes(
            "EURUSD", 0, M15 * 2, M15
        )
        self.assertEqual(len(quotes), 2)
        self.assertEqual({q.fact.bid for q in quotes}, {100, 101})

    def test_calendar_view_is_holdout_guarded(self):
        schedule = make_calendar_schedule(
            provider_event_key="holdout-event",
            currency="USD",
            title="CPI",
            impact="HIGH",
            scheduled_time_us=M15,
            all_day=False,
            reference_period="2026-09",
        )
        link = self.put_fact_link(
            schedule,
            locator="calendar-holdout",
            available_at_us=0,
            basis=AvailabilityBasis.SOURCE_STAMPED,
        )
        ds = self.dataset([self.member("CALENDAR_SCHEDULE", schedule, link)])
        registry = ResearchRegistry(self.store)
        exp = registry.register_experiment(
            {"hypothesis": "calendar"}, "ali", "cal-exp", "CONFIRMATORY"
        )
        segment = registry.add_holdout_segment("EURUSD", 0, M15 * 2)
        grant = registry.grant_holdout(
            exp.experiment_id, segment.segment_id, "ali", "cal-grant"
        )
        with self.assertRaises(HoldoutLocked):
            MarketView(self.store, ds.dataset_id).calendar_schedules(
                0, M15 * 2, M15 * 2
            )
        view = MarketView(
            self.store,
            ds.dataset_id,
            actor="ali",
            purpose="calendar-oos",
            grant_ids=(grant.grant_id,),
            request_key_prefix="calendar",
        )
        self.assertEqual(
            len(view.calendar_schedules(0, M15 * 2, M15 * 2)),
            1,
        )
        self.assertEqual(
            self.store.conn.execute(
                "SELECT route FROM research_exposures ORDER BY served_at_us DESC LIMIT 1"
            ).fetchone()[0],
            "MARKET_VIEW",
        )

    def test_market_and_outcome_views_guard_holdout_before_return(self):
        fact = self.bar()
        link = self.put_fact_link(fact, locator="holdout", available_at_us=M15)
        ds = self.dataset([self.member("BAR", fact, link)])

        registry = ResearchRegistry(self.store)
        exp = registry.register_experiment(
            {"hypothesis": "h"}, "ali", "exp", "CONFIRMATORY"
        )
        segment = registry.add_holdout_segment("EURUSD", 0, M15)
        grant = registry.grant_holdout(exp.experiment_id, segment.segment_id, "ali", "grant")

        with self.assertRaises(HoldoutLocked):
            MarketView(self.store, ds.dataset_id).bars(
                "EURUSD", "M15", "BID", 0, M15, M15
            )

        market = MarketView(
            self.store,
            ds.dataset_id,
            actor="ali",
            purpose="final-oos",
            grant_ids=(grant.grant_id,),
            request_key_prefix="market",
        )
        self.assertEqual(
            len(market.bars("EURUSD", "M15", "BID", 0, M15, M15)), 1
        )
        route = self.store.conn.execute(
            "SELECT route FROM research_exposures ORDER BY served_at_us LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(route, "MARKET_VIEW")

        second_exp = registry.register_experiment(
            {"hypothesis": "h2"}, "ali", "exp2", "CONFIRMATORY"
        )
        second_grant = registry.grant_holdout(
            second_exp.experiment_id, segment.segment_id, "ali", "grant2"
        )
        outcome = OutcomeView(
            self.store,
            ds.dataset_id,
            actor="ali",
            purpose="final-oos",
            grant_ids=(second_grant.grant_id,),
            request_key_prefix="outcome",
        )
        self.assertEqual(
            len(outcome.bars("EURUSD", "M15", "BID", 0, M15, M15)), 1
        )
        routes = {
            row[0] for row in self.store.conn.execute("SELECT route FROM research_exposures")
        }
        self.assertEqual(routes, {"MARKET_VIEW", "OUTCOME_VIEW"})

    def test_bar_fact_link_cannot_claim_availability_before_close(self):
        fact = self.bar()
        self.store.put(fact)
        bad = FactLink(
            fact.fact_id,
            self.obs1.obs_id,
            "bad-availability",
            COMP,
            M15 - 1,
            AvailabilityBasis.SOURCE_STAMPED,
            0,
        )
        bad.validate()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "BAR_AVAILABLE_BEFORE_CLOSE"):
            self.store.put(bad)

    def test_fact_and_dataset_ids_are_bound_to_content(self):
        fact = self.bar()
        with self.assertRaisesRegex(ValueError, "bar fact identity mismatch"):
            replace(fact, fact_id="fbar_" + "0" * 64).validate()
        link = self.put_fact_link(fact, locator="identity", available_at_us=M15)
        ds = self.dataset([self.member("BAR", fact, link)])
        with self.assertRaisesRegex(ValueError, "dataset identity mismatch"):
            replace(ds, dataset_id="ds_" + "0" * 64).validate()

    def test_data_evidence_immutable_and_schema_verified(self):
        fact = self.bar()
        link = self.put_fact_link(fact, locator="immutable", available_at_us=M15)
        ds = self.dataset([self.member("BAR", fact, link)])
        verify(self.store.root)

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                "UPDATE data_bar_facts SET close=close WHERE fact_id=?", (fact.fact_id,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                "DELETE FROM data_datasets WHERE dataset_id=?", (ds.dataset_id,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                "INSERT OR REPLACE INTO data_fact_links "
                "SELECT * FROM data_fact_links WHERE fact_id=?",
                (fact.fact_id,),
            )


if __name__ == "__main__":
    unittest.main()
