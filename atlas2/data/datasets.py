"""Canonical fact constructors and frozen dataset identity for P0-4."""
from __future__ import annotations

from dataclasses import asdict

from atlas2.core.canonical import canonical_json_text, domain_digest
from atlas2.core.ids import make_id
from atlas2.core.units import canonical_decimal_text
from atlas2.model.data import (
    BarFact,
    CalendarScheduleFact,
    CalendarValueFact,
    DatasetMembership,
    DatasetVersion,
    QuoteFact,
)
from atlas2.store.repository import Store, StoreConflict, ConflictKind


def make_bar_fact(**fields) -> BarFact:
    content = {
        key: fields[key]
        for key in (
            "instrument_id",
            "timeframe",
            "price_side",
            "open_time_us",
            "close_time_us",
            "open",
            "high",
            "low",
            "close",
            "tick_volume",
            "real_volume",
            "spread_points",
            "spread_semantics",
            "instrument_spec_id",
        )
    }
    model = BarFact(make_id("fbar", "bar-fact-v1", content), **content)
    model.validate()
    return model


def make_quote_fact(**fields) -> QuoteFact:
    content = {
        key: fields[key]
        for key in (
            "instrument_id",
            "time_us",
            "source_seq",
            "bid",
            "ask",
            "bid_volume",
            "ask_volume",
            "instrument_spec_id",
        )
    }
    model = QuoteFact(make_id("fqt", "quote-fact-v1", content), **content)
    model.validate()
    return model


def make_calendar_schedule(**fields) -> CalendarScheduleFact:
    content = {
        key: fields[key]
        for key in (
            "provider_event_key",
            "currency",
            "title",
            "impact",
            "scheduled_time_us",
            "all_day",
            "reference_period",
        )
    }
    model = CalendarScheduleFact(make_id("fcs", "calendar-schedule-v1", content), **content)
    model.validate()
    return model


def make_calendar_value(**fields) -> CalendarValueFact:
    content = {
        key: fields[key]
        for key in ("provider_event_key", "value_kind", "value_text", "unit")
    }
    content["value_text"] = canonical_decimal_text(content["value_text"])
    model = CalendarValueFact(make_id("fcv", "calendar-value-v1", content), **content)
    model.validate()
    return model


def canonical_membership_rows(rows) -> list[tuple[str, str, str, str]]:
    normalized = []
    seen = set()
    for row in rows:
        if type(row) is not tuple or len(row) != 4:
            raise ValueError("membership row must be (fact_kind,fact_id,obs_id,locator)")
        key = tuple(row)
        if key in seen:
            raise ValueError("duplicate dataset membership row")
        seen.add(key)
        normalized.append(key)
    if not normalized:
        raise ValueError("dataset membership cannot be empty")
    return sorted(normalized)


def membership_digest(rows) -> str:
    return domain_digest("dataset-membership-v1", [list(row) for row in canonical_membership_rows(rows)])


def freeze_dataset(
    store: Store,
    rows,
    *,
    coverage: object,
    causal_policy: object,
    htf_policy: object,
    precedence_policy: object,
    clock_profile_id: str,
    instrument_specs: object,
    tzdata_version: str,
    display_name: str,
    built_at_us: int,
) -> DatasetVersion:
    members = canonical_membership_rows(rows)
    digest = membership_digest(members)
    identity = {
        "membership_digest": digest,
        "coverage": coverage,
        "causal_policy": causal_policy,
        "htf_policy": htf_policy,
        "precedence_policy": precedence_policy,
        "clock_profile_id": clock_profile_id,
        "instrument_specs": instrument_specs,
        "tzdata_version": tzdata_version,
    }
    dataset_id = make_id("ds", "dataset-version-v1", identity)
    model = DatasetVersion(
        dataset_id,
        digest,
        canonical_json_text(coverage),
        canonical_json_text(causal_policy),
        canonical_json_text(htf_policy),
        canonical_json_text(precedence_policy),
        clock_profile_id,
        canonical_json_text(instrument_specs),
        tzdata_version,
        display_name,
        built_at_us,
    )
    model.validate()

    membership_models = [
        DatasetMembership(dataset_id, kind, fact_id, obs_id, locator)
        for kind, fact_id, obs_id, locator in members
    ]
    for member in membership_models:
        member.validate()

    existing = store.conn.execute(
        "SELECT * FROM data_datasets WHERE dataset_id=?", (dataset_id,)
    ).fetchone()
    if existing is not None:
        identity_columns = (
            "membership_digest",
            "coverage_json",
            "causal_policy_json",
            "htf_policy_json",
            "precedence_policy_json",
            "clock_profile_id",
            "instrument_specs_json",
            "tzdata_version",
        )
        expected = asdict(model)
        if any(existing[column] != expected[column] for column in identity_columns):
            raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        stored = [
            tuple(row)
            for row in store.conn.execute(
                "SELECT fact_kind,fact_id,obs_id,locator "
                "FROM data_dataset_membership WHERE dataset_id=? "
                "ORDER BY fact_kind,fact_id,obs_id,locator",
                (dataset_id,),
            )
        ]
        if stored != members:
            raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        seal = store.conn.execute(
            "SELECT child_set_digest FROM sys_seals "
            "WHERE aggregate_kind='data_datasets' AND aggregate_id=?",
            (dataset_id,),
        ).fetchone()
        if seal is None or seal[0] != store.child_digest('data_datasets', dataset_id):
            raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
        return DatasetVersion(**dict(existing))

    store.put_many_and_seal(
        [model, *membership_models],
        'data_datasets',
        dataset_id,
    )
    return model
