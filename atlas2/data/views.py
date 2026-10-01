"""Causal read views for frozen P0-4 datasets."""
from __future__ import annotations

from dataclasses import dataclass

from atlas2.core.enums import RunMode, ViewClass
from atlas2.core.taint import Taint
from atlas2.model.data import BarFact, QuoteFact
from atlas2.research.holdout import guard_read
from atlas2.store.repository import Store


@dataclass(frozen=True, slots=True)
class VisibleBar:
    fact: BarFact
    available_at_us: int
    taint: int = 0


@dataclass(frozen=True, slots=True)
class VisibleQuote:
    fact: QuoteFact
    available_at_us: int
    taint: int = 0


@dataclass(frozen=True, slots=True)
class VisibleCalendarFact:
    fact_kind: str
    fact_id: str
    available_at_us: int | None
    taint: int
    content: dict


def _knowledge_time(row, mode: RunMode) -> int | None:
    available = row["available_at_us"]
    if available is None:
        return None
    if mode is RunMode.FORWARD:
        return max(available, row["acquired_at_us"])
    return available


def _select_rows(
    rows,
    *,
    as_of_us: int,
    mode: RunMode,
    view_class: ViewClass,
    natural_key,
    unknown_taint: Taint,
):
    if not isinstance(mode, RunMode):
        raise ValueError("mode must be RunMode")
    if not isinstance(view_class, ViewClass):
        raise ValueError("view_class must be ViewClass")

    per_fact: dict[str, tuple[int | None, object, int]] = {}
    unknown_rows: dict[str, object] = {}

    for row in rows:
        fact_id = row["fact_id"]
        if row["availability_basis"] == "UNKNOWN":
            unknown_rows.setdefault(fact_id, row)
            continue
        knowledge = _knowledge_time(row, mode)
        if knowledge is None or knowledge > as_of_us:
            continue
        current = per_fact.get(fact_id)
        if current is None or current[0] is None or knowledge < current[0]:
            per_fact[fact_id] = (knowledge, row, 0)

    if view_class is ViewClass.NON_PIT:
        for fact_id, row in unknown_rows.items():
            if fact_id not in per_fact:
                per_fact[fact_id] = (None, row, int(unknown_taint))

    by_natural_key = {}
    for fact_id, (available, row, taint) in per_fact.items():
        key = natural_key(row)
        rank = (available if available is not None else -(2**63), fact_id)
        current = by_natural_key.get(key)
        if current is None or rank > current[0]:
            by_natural_key[key] = (rank, available, row, taint)
    return list(by_natural_key.values())


class _BaseView:
    route = ""

    def __init__(
        self,
        store: Store,
        dataset_id: str,
        *,
        mode: RunMode = RunMode.REPLAY,
        actor: str = "system",
        purpose: str = "research",
        grant_ids: tuple[str, ...] = (),
        request_key_prefix: str = "view",
    ):
        self.store = store
        self.conn = store.conn
        self.dataset_id = dataset_id
        self.mode = mode
        self.actor = actor
        self.purpose = purpose
        self.grant_ids = grant_ids
        self.request_key_prefix = request_key_prefix
        if not isinstance(mode, RunMode):
            raise ValueError("mode must be RunMode")
        if not self.conn.execute(
            "SELECT 1 FROM data_datasets WHERE dataset_id=?", (dataset_id,)
        ).fetchone():
            raise ValueError("unknown dataset")

    def _guard(self, instrument_id: str, start_us: int, end_us: int, suffix: str) -> None:
        guard_read(
            self.store,
            instrument_id=instrument_id,
            start_us=start_us,
            end_us=end_us,
            route=self.route,
            actor=self.actor,
            purpose=self.purpose,
            grant_ids=self.grant_ids,
            request_key_prefix=f"{self.request_key_prefix}:{suffix}",
        )

    def _guard_all_holdouts(self, start_us: int, end_us: int, suffix: str) -> None:
        instruments = [
            row[0]
            for row in self.conn.execute(
                "SELECT DISTINCT instrument_id FROM research_holdout_segments "
                "WHERE start_us<? AND end_us>? ORDER BY instrument_id",
                (end_us, start_us),
            )
        ]
        for instrument_id in instruments:
            self._guard(
                instrument_id,
                start_us,
                end_us,
                f"calendar:{instrument_id}:{suffix}",
            )

    def _bar_rows(self, instrument_id, timeframe, price_side, start_us, end_us):
        return self.conn.execute(
            """SELECT b.*,l.available_at_us,l.availability_basis,o.acquired_at_us
               FROM data_dataset_membership m
               JOIN data_bar_facts b ON b.fact_id=m.fact_id
               JOIN data_fact_links l
                 ON l.fact_id=m.fact_id AND l.obs_id=m.obs_id AND l.locator=m.locator
               JOIN source_observations o ON o.obs_id=m.obs_id
               WHERE m.dataset_id=? AND m.fact_kind='BAR'
                 AND b.instrument_id=? AND b.timeframe=? AND b.price_side=?
                 AND b.open_time_us>=? AND b.open_time_us<?
               ORDER BY b.open_time_us,b.fact_id,l.available_at_us,o.acquired_at_us""",
            (self.dataset_id, instrument_id, timeframe, price_side, start_us, end_us),
        ).fetchall()

    def _read_bars(
        self,
        instrument_id: str,
        timeframe: str,
        price_side: str,
        start_us: int,
        end_us: int,
        as_of_us: int,
        view_class: ViewClass,
    ) -> list[VisibleBar]:
        rows = self._bar_rows(instrument_id, timeframe, price_side, start_us, end_us)
        chosen = _select_rows(
            rows,
            as_of_us=as_of_us,
            mode=self.mode,
            view_class=view_class,
            natural_key=lambda r: (
                r["instrument_id"],
                r["timeframe"],
                r["price_side"],
                r["open_time_us"],
            ),
            unknown_taint=Taint.UNVERIFIED_REPORT_AVAILABILITY,
        )
        result = []
        for _, available, row, taint in sorted(
            chosen, key=lambda item: (item[2]["open_time_us"], item[2]["fact_id"])
        ):
            fact = BarFact(
                row["fact_id"],
                row["instrument_id"],
                row["timeframe"],
                row["price_side"],
                row["open_time_us"],
                row["close_time_us"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["tick_volume"],
                row["real_volume"],
                row["spread_points"],
                row["spread_semantics"],
                row["instrument_spec_id"],
            )
            fact.validate()
            result.append(VisibleBar(fact, as_of_us if available is None else available, taint))
        return result


class MarketView(_BaseView):
    route = "MARKET_VIEW"

    def bars(
        self,
        instrument_id: str,
        timeframe: str,
        price_side: str,
        start_us: int,
        end_us: int,
        as_of_us: int,
        *,
        view_class: ViewClass = ViewClass.PIT,
    ) -> list[VisibleBar]:
        self._guard(
            instrument_id,
            start_us,
            end_us,
            f"bars:{instrument_id}:{timeframe}:{price_side}:{start_us}:{end_us}:{as_of_us}",
        )
        return self._read_bars(
            instrument_id, timeframe, price_side, start_us, end_us, as_of_us, view_class
        )

    def quotes(
        self,
        instrument_id: str,
        start_us: int,
        end_us: int,
        as_of_us: int,
        *,
        view_class: ViewClass = ViewClass.PIT,
    ) -> list[VisibleQuote]:
        self._guard(
            instrument_id,
            start_us,
            end_us,
            f"quotes:{instrument_id}:{start_us}:{end_us}:{as_of_us}",
        )
        rows = self.conn.execute(
            """SELECT q.*,l.available_at_us,l.availability_basis,o.acquired_at_us
               FROM data_dataset_membership m
               JOIN data_quote_facts q ON q.fact_id=m.fact_id
               JOIN data_fact_links l
                 ON l.fact_id=m.fact_id AND l.obs_id=m.obs_id AND l.locator=m.locator
               JOIN source_observations o ON o.obs_id=m.obs_id
               WHERE m.dataset_id=? AND m.fact_kind='QUOTE'
                 AND q.instrument_id=? AND q.time_us>=? AND q.time_us<?
               ORDER BY q.time_us,q.source_seq,q.fact_id""",
            (self.dataset_id, instrument_id, start_us, end_us),
        ).fetchall()

        def key(row):
            if row["source_seq"] is None:
                return (row["instrument_id"], row["time_us"], None, row["fact_id"])
            return (row["instrument_id"], row["time_us"], row["source_seq"])

        chosen = _select_rows(
            rows,
            as_of_us=as_of_us,
            mode=self.mode,
            view_class=view_class,
            natural_key=key,
            unknown_taint=Taint.UNVERIFIED_REPORT_AVAILABILITY,
        )
        result = []
        for _, available, row, taint in sorted(
            chosen,
            key=lambda item: (
                item[2]["time_us"],
                -1 if item[2]["source_seq"] is None else item[2]["source_seq"],
                item[2]["fact_id"],
            ),
        ):
            fact = QuoteFact(
                row["fact_id"],
                row["instrument_id"],
                row["time_us"],
                row["source_seq"],
                row["bid"],
                row["ask"],
                row["bid_volume"],
                row["ask_volume"],
                row["instrument_spec_id"],
            )
            fact.validate()
            result.append(VisibleQuote(fact, as_of_us if available is None else available, taint))
        return result

    def calendar_schedules(
        self,
        start_us: int,
        end_us: int,
        as_of_us: int,
        *,
        currencies: tuple[str, ...] = (),
        view_class: ViewClass = ViewClass.PIT,
    ) -> list[VisibleCalendarFact]:
        self._guard_all_holdouts(
            start_us,
            end_us,
            f"schedules:{start_us}:{end_us}:{as_of_us}",
        )
        params = [self.dataset_id, start_us, end_us]
        currency_sql = ""
        if currencies:
            currency_sql = " AND c.currency IN (" + ",".join("?" for _ in currencies) + ")"
            params.extend(currencies)
        rows = self.conn.execute(
            f"""SELECT c.*,l.available_at_us,l.availability_basis,o.acquired_at_us
                FROM data_dataset_membership m
                JOIN data_calendar_schedule_facts c ON c.fact_id=m.fact_id
                JOIN data_fact_links l
                  ON l.fact_id=m.fact_id AND l.obs_id=m.obs_id AND l.locator=m.locator
                JOIN source_observations o ON o.obs_id=m.obs_id
                WHERE m.dataset_id=? AND m.fact_kind='CALENDAR_SCHEDULE'
                  AND c.scheduled_time_us>=? AND c.scheduled_time_us<? {currency_sql}
                ORDER BY c.provider_event_key,c.fact_id""",
            params,
        ).fetchall()
        chosen = _select_rows(
            rows,
            as_of_us=as_of_us,
            mode=self.mode,
            view_class=view_class,
            natural_key=lambda r: r["provider_event_key"],
            unknown_taint=Taint.NON_PIT_MACRO,
        )
        return [
            VisibleCalendarFact(
                "CALENDAR_SCHEDULE",
                row["fact_id"],
                available,
                taint,
                dict(row),
            )
            for _, available, row, taint in sorted(
                chosen,
                key=lambda item: (
                    item[2]["scheduled_time_us"],
                    item[2]["provider_event_key"],
                    item[2]["fact_id"],
                ),
            )
        ]

    def calendar_values(
        self,
        provider_event_keys: tuple[str, ...],
        start_us: int,
        end_us: int,
        as_of_us: int,
        *,
        view_class: ViewClass = ViewClass.PIT,
    ) -> list[VisibleCalendarFact]:
        if not provider_event_keys:
            return []
        self._guard_all_holdouts(
            start_us,
            end_us,
            f"values:{start_us}:{end_us}:{as_of_us}:{','.join(provider_event_keys)}",
        )
        sql = (
            "SELECT v.*,l.available_at_us,l.availability_basis,o.acquired_at_us "
            "FROM data_dataset_membership m "
            "JOIN data_calendar_value_facts v ON v.fact_id=m.fact_id "
            "JOIN data_fact_links l "
            "ON l.fact_id=m.fact_id AND l.obs_id=m.obs_id AND l.locator=m.locator "
            "JOIN source_observations o ON o.obs_id=m.obs_id "
            "WHERE m.dataset_id=? AND m.fact_kind='CALENDAR_VALUE' "
            "AND v.provider_event_key IN ("
            + ",".join("?" for _ in provider_event_keys)
            + ") ORDER BY v.provider_event_key,v.value_kind,v.fact_id"
        )
        rows = self.conn.execute(sql, (self.dataset_id, *provider_event_keys)).fetchall()
        chosen = _select_rows(
            rows,
            as_of_us=as_of_us,
            mode=self.mode,
            view_class=view_class,
            natural_key=lambda r: (r["provider_event_key"], r["value_kind"]),
            unknown_taint=Taint.NON_PIT_MACRO,
        )
        return [
            VisibleCalendarFact(
                "CALENDAR_VALUE",
                row["fact_id"],
                available,
                taint,
                dict(row),
            )
            for _, available, row, taint in sorted(
                chosen,
                key=lambda item: (
                    item[2]["provider_event_key"],
                    item[2]["value_kind"],
                    item[2]["fact_id"],
                ),
            )
        ]


class OutcomeView(_BaseView):
    route = "OUTCOME_VIEW"

    def bars(
        self,
        instrument_id: str,
        timeframe: str,
        price_side: str,
        start_us: int,
        end_us: int,
        as_of_us: int,
    ) -> list[VisibleBar]:
        self._guard(
            instrument_id,
            start_us,
            end_us,
            f"bars:{instrument_id}:{timeframe}:{price_side}:{start_us}:{end_us}:{as_of_us}",
        )
        return self._read_bars(
            instrument_id,
            timeframe,
            price_side,
            start_us,
            end_us,
            as_of_us,
            ViewClass.PIT,
        )
