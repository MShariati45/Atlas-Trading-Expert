CREATE TABLE data_bar_facts (
 fact_id TEXT PRIMARY KEY,
 instrument_id TEXT NOT NULL,
 timeframe TEXT NOT NULL CHECK(timeframe IN ('M1','M5','M15','H1','H4','D1')),
 price_side TEXT NOT NULL CHECK(price_side IN ('BID','ASK','MID')),
 open_time_us INTEGER NOT NULL,
 close_time_us INTEGER NOT NULL,
 open INTEGER NOT NULL,
 high INTEGER NOT NULL,
 low INTEGER NOT NULL,
 close INTEGER NOT NULL,
 tick_volume INTEGER NOT NULL CHECK(tick_volume>=0),
 real_volume INTEGER CHECK(real_volume IS NULL OR real_volume>=0),
 spread_points INTEGER CHECK(spread_points IS NULL OR spread_points>=0),
 spread_semantics TEXT,
 instrument_spec_id TEXT NOT NULL,
 CHECK(close_time_us>open_time_us),
 CHECK(low<=open AND low<=close AND high>=open AND high>=close)
) STRICT;
CREATE INDEX data_bar_natural_key ON data_bar_facts(instrument_id,timeframe,price_side,open_time_us);

CREATE TABLE data_quote_facts (
 fact_id TEXT PRIMARY KEY,
 instrument_id TEXT NOT NULL,
 time_us INTEGER NOT NULL,
 source_seq INTEGER CHECK(source_seq IS NULL OR source_seq>=0),
 bid INTEGER NOT NULL,
 ask INTEGER NOT NULL,
 bid_volume INTEGER CHECK(bid_volume IS NULL OR bid_volume>=0),
 ask_volume INTEGER CHECK(ask_volume IS NULL OR ask_volume>=0),
 instrument_spec_id TEXT NOT NULL,
 CHECK(ask>=bid)
) STRICT;
CREATE INDEX data_quote_natural_key ON data_quote_facts(instrument_id,time_us,source_seq);

CREATE TABLE data_calendar_schedule_facts (
 fact_id TEXT PRIMARY KEY,
 provider_event_key TEXT NOT NULL,
 currency TEXT NOT NULL,
 title TEXT NOT NULL,
 impact TEXT NOT NULL,
 scheduled_time_us INTEGER,
 all_day INTEGER NOT NULL CHECK(all_day IN (0,1)),
 reference_period TEXT
) STRICT;
CREATE INDEX data_calendar_schedule_natural_key ON data_calendar_schedule_facts(provider_event_key);

CREATE TABLE data_calendar_value_facts (
 fact_id TEXT PRIMARY KEY,
 provider_event_key TEXT NOT NULL,
 value_kind TEXT NOT NULL CHECK(value_kind IN ('ACTUAL','FORECAST','PREVIOUS','REVISED_PREVIOUS')),
 value_text TEXT NOT NULL,
 unit TEXT
) STRICT;
CREATE INDEX data_calendar_value_natural_key ON data_calendar_value_facts(provider_event_key,value_kind);

CREATE TABLE data_fact_links (
 fact_id TEXT NOT NULL,
 obs_id TEXT NOT NULL REFERENCES source_observations(obs_id),
 locator TEXT NOT NULL,
 normalizer_version_id TEXT NOT NULL,
 available_at_us INTEGER,
 availability_basis TEXT NOT NULL CHECK(availability_basis IN ('SOURCE_STAMPED','BAR_CLOSE_RULE','OBSERVED_BY_ATLAS','DERIVED','UNKNOWN')),
 quality_flags INTEGER NOT NULL DEFAULT 0 CHECK(quality_flags>=0),
 PRIMARY KEY(fact_id,obs_id,locator),
 CHECK((availability_basis='UNKNOWN' AND available_at_us IS NULL) OR (availability_basis<>'UNKNOWN' AND available_at_us IS NOT NULL))
) STRICT;
CREATE INDEX data_fact_links_availability ON data_fact_links(fact_id,available_at_us);

CREATE TRIGGER data_bar_link_not_before_close BEFORE INSERT ON data_fact_links
WHEN NEW.availability_basis<>'UNKNOWN'
 AND EXISTS(
   SELECT 1 FROM data_bar_facts b
   WHERE b.fact_id=NEW.fact_id AND NEW.available_at_us<b.close_time_us
 )
BEGIN SELECT RAISE(ABORT,'BAR_AVAILABLE_BEFORE_CLOSE'); END;

CREATE TRIGGER data_fact_link_requires_fact BEFORE INSERT ON data_fact_links
WHEN NOT EXISTS(SELECT 1 FROM data_bar_facts WHERE fact_id=NEW.fact_id)
 AND NOT EXISTS(SELECT 1 FROM data_quote_facts WHERE fact_id=NEW.fact_id)
 AND NOT EXISTS(SELECT 1 FROM data_calendar_schedule_facts WHERE fact_id=NEW.fact_id)
 AND NOT EXISTS(SELECT 1 FROM data_calendar_value_facts WHERE fact_id=NEW.fact_id)
BEGIN SELECT RAISE(ABORT,'UNKNOWN_FACT'); END;

CREATE TABLE data_datasets (
 dataset_id TEXT PRIMARY KEY,
 membership_digest TEXT NOT NULL CHECK(length(membership_digest)=64),
 coverage_json TEXT NOT NULL,
 causal_policy_json TEXT NOT NULL,
 htf_policy_json TEXT NOT NULL,
 precedence_policy_json TEXT NOT NULL,
 clock_profile_id TEXT NOT NULL,
 instrument_specs_json TEXT NOT NULL,
 tzdata_version TEXT NOT NULL,
 display_name TEXT NOT NULL,
 built_at_us INTEGER NOT NULL
) STRICT;

CREATE TABLE data_dataset_membership (
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 fact_kind TEXT NOT NULL CHECK(fact_kind IN ('BAR','QUOTE','CALENDAR_SCHEDULE','CALENDAR_VALUE')),
 fact_id TEXT NOT NULL,
 obs_id TEXT NOT NULL,
 locator TEXT NOT NULL,
 PRIMARY KEY(dataset_id,fact_kind,fact_id,obs_id,locator),
 FOREIGN KEY(fact_id,obs_id,locator) REFERENCES data_fact_links(fact_id,obs_id,locator)
) STRICT;
CREATE INDEX data_dataset_membership_lookup ON data_dataset_membership(dataset_id,fact_kind,fact_id);

DROP TRIGGER seal_parent_exists;
CREATE TRIGGER seal_parent_exists BEFORE INSERT ON sys_seals BEGIN
 SELECT CASE
 WHEN NEW.aggregate_kind='run_manifests' AND EXISTS(SELECT 1 FROM run_manifests WHERE manifest_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='run_attempt_starts' AND EXISTS(SELECT 1 FROM run_attempt_starts WHERE attempt_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='data_datasets' AND EXISTS(SELECT 1 FROM data_datasets WHERE dataset_id=NEW.aggregate_id) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_SEAL_PARENT') END;
END;
CREATE TRIGGER sealed_dataset_children BEFORE INSERT ON data_dataset_membership
WHEN EXISTS(
 SELECT 1 FROM sys_seals
 WHERE aggregate_kind='data_datasets' AND aggregate_id=NEW.dataset_id
)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;

CREATE TRIGGER data_membership_kind BEFORE INSERT ON data_dataset_membership
WHEN (NEW.fact_kind='BAR' AND NOT EXISTS(SELECT 1 FROM data_bar_facts WHERE fact_id=NEW.fact_id))
  OR (NEW.fact_kind='QUOTE' AND NOT EXISTS(SELECT 1 FROM data_quote_facts WHERE fact_id=NEW.fact_id))
  OR (NEW.fact_kind='CALENDAR_SCHEDULE' AND NOT EXISTS(SELECT 1 FROM data_calendar_schedule_facts WHERE fact_id=NEW.fact_id))
  OR (NEW.fact_kind='CALENDAR_VALUE' AND NOT EXISTS(SELECT 1 FROM data_calendar_value_facts WHERE fact_id=NEW.fact_id))
BEGIN SELECT RAISE(ABORT,'FACT_KIND_MISMATCH'); END;

CREATE TRIGGER immut_data_bar_facts_update BEFORE UPDATE ON data_bar_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_bar_facts_delete BEFORE DELETE ON data_bar_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_bar_facts_insert BEFORE INSERT ON data_bar_facts WHEN EXISTS(SELECT 1 FROM data_bar_facts WHERE fact_id=NEW.fact_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_quote_facts_update BEFORE UPDATE ON data_quote_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_quote_facts_delete BEFORE DELETE ON data_quote_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_quote_facts_insert BEFORE INSERT ON data_quote_facts WHEN EXISTS(SELECT 1 FROM data_quote_facts WHERE fact_id=NEW.fact_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_calendar_schedule_facts_update BEFORE UPDATE ON data_calendar_schedule_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_calendar_schedule_facts_delete BEFORE DELETE ON data_calendar_schedule_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_calendar_schedule_facts_insert BEFORE INSERT ON data_calendar_schedule_facts WHEN EXISTS(SELECT 1 FROM data_calendar_schedule_facts WHERE fact_id=NEW.fact_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_calendar_value_facts_update BEFORE UPDATE ON data_calendar_value_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_calendar_value_facts_delete BEFORE DELETE ON data_calendar_value_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_calendar_value_facts_insert BEFORE INSERT ON data_calendar_value_facts WHEN EXISTS(SELECT 1 FROM data_calendar_value_facts WHERE fact_id=NEW.fact_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_fact_links_update BEFORE UPDATE ON data_fact_links BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_fact_links_delete BEFORE DELETE ON data_fact_links BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_fact_links_insert BEFORE INSERT ON data_fact_links
WHEN EXISTS(SELECT 1 FROM data_fact_links WHERE fact_id=NEW.fact_id AND obs_id=NEW.obs_id AND locator=NEW.locator)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_datasets_update BEFORE UPDATE ON data_datasets BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_datasets_delete BEFORE DELETE ON data_datasets BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_datasets_insert BEFORE INSERT ON data_datasets WHEN EXISTS(SELECT 1 FROM data_datasets WHERE dataset_id=NEW.dataset_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_dataset_membership_update BEFORE UPDATE ON data_dataset_membership BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_dataset_membership_delete BEFORE DELETE ON data_dataset_membership BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_data_dataset_membership_insert BEFORE INSERT ON data_dataset_membership
WHEN EXISTS(SELECT 1 FROM data_dataset_membership WHERE dataset_id=NEW.dataset_id AND fact_kind=NEW.fact_kind AND fact_id=NEW.fact_id AND obs_id=NEW.obs_id AND locator=NEW.locator)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
