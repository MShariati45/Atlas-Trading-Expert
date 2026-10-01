CREATE TABLE research_preregistrations (prereg_digest TEXT PRIMARY KEY CHECK(length(prereg_digest)=64), payload_json TEXT NOT NULL) STRICT;
CREATE TRIGGER immut_research_preregistrations_update BEFORE UPDATE ON research_preregistrations
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_preregistrations_delete BEFORE DELETE ON research_preregistrations
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_preregistrations_insert BEFORE INSERT ON research_preregistrations
WHEN EXISTS(SELECT 1 FROM research_preregistrations WHERE prereg_digest=NEW.prereg_digest)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_experiments (experiment_id TEXT PRIMARY KEY, prereg_digest TEXT NOT NULL REFERENCES research_preregistrations, registered_by TEXT NOT NULL, request_key TEXT NOT NULL, experiment_type TEXT NOT NULL CHECK(experiment_type IN ('EXPLORATORY','CONFIRMATORY','PROMOTION_REVIEW','LABEL_STUDY','ENGINEERING')), registered_at_us INTEGER NOT NULL, UNIQUE(registered_by,request_key)) STRICT;
CREATE TRIGGER immut_research_experiments_update BEFORE UPDATE ON research_experiments
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_experiments_delete BEFORE DELETE ON research_experiments
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_experiments_insert BEFORE INSERT ON research_experiments
WHEN EXISTS(SELECT 1 FROM research_experiments WHERE experiment_id=NEW.experiment_id OR (registered_by=NEW.registered_by AND request_key=NEW.request_key))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_amendments (amendment_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES research_experiments, sequence INTEGER NOT NULL CHECK(sequence>0), parent_effective_digest TEXT NOT NULL REFERENCES research_preregistrations, new_payload_digest TEXT NOT NULL REFERENCES research_preregistrations, recorded_at_us INTEGER NOT NULL, UNIQUE(experiment_id,sequence)) STRICT;
CREATE TRIGGER immut_research_amendments_update BEFORE UPDATE ON research_amendments
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_amendments_delete BEFORE DELETE ON research_amendments
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_amendments_insert BEFORE INSERT ON research_amendments
WHEN EXISTS(SELECT 1 FROM research_amendments WHERE amendment_id=NEW.amendment_id OR (experiment_id=NEW.experiment_id AND sequence=NEW.sequence))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_trials (trial_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES research_experiments, trial_index INTEGER NOT NULL CHECK(trial_index>0), parameters_json TEXT NOT NULL, UNIQUE(experiment_id,trial_index)) STRICT;
CREATE TRIGGER immut_research_trials_update BEFORE UPDATE ON research_trials
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_trials_delete BEFORE DELETE ON research_trials
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_trials_insert BEFORE INSERT ON research_trials
WHEN EXISTS(SELECT 1 FROM research_trials WHERE trial_id=NEW.trial_id OR (experiment_id=NEW.experiment_id AND trial_index=NEW.trial_index))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_trial_events (event_id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES research_trials, event TEXT NOT NULL CHECK(event IN ('PLANNED','STARTED','FAILED','ABANDONED','COMPLETED','INSPECTED','SELECTED','REPLICATED')), effective_prereg_digest TEXT NOT NULL REFERENCES research_preregistrations, amendment_sequence INTEGER NOT NULL CHECK(amendment_sequence>=0), evidence_order INTEGER NOT NULL CHECK(evidence_order>0), recorded_at_us INTEGER NOT NULL) STRICT;
CREATE TRIGGER immut_research_trial_events_update BEFORE UPDATE ON research_trial_events
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_trial_events_delete BEFORE DELETE ON research_trial_events
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_trial_events_insert BEFORE INSERT ON research_trial_events
WHEN EXISTS(SELECT 1 FROM research_trial_events WHERE event_id=NEW.event_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_trial_results (result_id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES research_trials, result_kind TEXT NOT NULL CHECK(result_kind IN ('PRIMARY','REPLICATION')), attempt_id TEXT NOT NULL REFERENCES run_attempt_starts, effective_prereg_digest TEXT NOT NULL REFERENCES research_preregistrations, payload_json TEXT NOT NULL, recorded_at_us INTEGER NOT NULL, UNIQUE(trial_id,attempt_id)) STRICT;
CREATE TRIGGER immut_research_trial_results_update BEFORE UPDATE ON research_trial_results
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_trial_results_delete BEFORE DELETE ON research_trial_results
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_trial_results_insert BEFORE INSERT ON research_trial_results
WHEN EXISTS(SELECT 1 FROM research_trial_results WHERE result_id=NEW.result_id OR (trial_id=NEW.trial_id AND (attempt_id=NEW.attempt_id OR (result_kind='PRIMARY' AND NEW.result_kind='PRIMARY'))))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_decisions (decision_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL UNIQUE REFERENCES research_experiments, payload_json TEXT NOT NULL, recorded_at_us INTEGER NOT NULL) STRICT;
CREATE TRIGGER immut_research_decisions_update BEFORE UPDATE ON research_decisions
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_decisions_delete BEFORE DELETE ON research_decisions
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_decisions_insert BEFORE INSERT ON research_decisions
WHEN EXISTS(SELECT 1 FROM research_decisions WHERE decision_id=NEW.decision_id OR experiment_id=NEW.experiment_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_holdout_segments (segment_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, start_us INTEGER NOT NULL, end_us INTEGER NOT NULL CHECK(end_us>start_us), purpose TEXT NOT NULL CHECK(purpose='FINAL_OOS'), UNIQUE(instrument_id,start_us,end_us,purpose)) STRICT;
CREATE TRIGGER immut_research_holdout_segments_update BEFORE UPDATE ON research_holdout_segments
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_holdout_segments_delete BEFORE DELETE ON research_holdout_segments
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_holdout_segments_insert BEFORE INSERT ON research_holdout_segments
WHEN EXISTS(SELECT 1 FROM research_holdout_segments WHERE segment_id=NEW.segment_id OR (instrument_id=NEW.instrument_id AND start_us=NEW.start_us AND end_us=NEW.end_us AND purpose=NEW.purpose))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_holdout_grants (grant_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES research_experiments, segment_id TEXT NOT NULL REFERENCES research_holdout_segments, effective_prereg_digest TEXT NOT NULL REFERENCES research_preregistrations, granted_by TEXT NOT NULL, request_key TEXT NOT NULL, granted_at_us INTEGER NOT NULL, UNIQUE(granted_by,request_key)) STRICT;
CREATE TRIGGER immut_research_holdout_grants_update BEFORE UPDATE ON research_holdout_grants
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_holdout_grants_delete BEFORE DELETE ON research_holdout_grants
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_holdout_grants_insert BEFORE INSERT ON research_holdout_grants
WHEN EXISTS(SELECT 1 FROM research_holdout_grants WHERE grant_id=NEW.grant_id OR (granted_by=NEW.granted_by AND request_key=NEW.request_key))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TABLE research_exposures (exposure_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES research_holdout_segments, actor TEXT NOT NULL, purpose TEXT NOT NULL, route TEXT NOT NULL CHECK(route IN ('MARKET_VIEW','OUTCOME_VIEW','LABEL_TASK','EXPORT')), start_us INTEGER NOT NULL, end_us INTEGER NOT NULL CHECK(end_us>start_us), grant_id TEXT NOT NULL REFERENCES research_holdout_grants, batch_session_id TEXT NOT NULL, effective_prereg_digest TEXT NOT NULL REFERENCES research_preregistrations, amendment_sequence INTEGER NOT NULL CHECK(amendment_sequence>=0), evidence_order INTEGER NOT NULL CHECK(evidence_order>0), served_at_us INTEGER NOT NULL) STRICT;
CREATE TRIGGER immut_research_exposures_update BEFORE UPDATE ON research_exposures
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_exposures_delete BEFORE DELETE ON research_exposures
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_research_exposures_insert BEFORE INSERT ON research_exposures
WHEN EXISTS(SELECT 1 FROM research_exposures WHERE exposure_id=NEW.exposure_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE UNIQUE INDEX research_one_primary ON research_trial_results(trial_id) WHERE result_kind='PRIMARY';
CREATE UNIQUE INDEX research_one_started ON research_trial_events(trial_id) WHERE event='STARTED';
CREATE TRIGGER research_amendment_lineage BEFORE INSERT ON research_amendments
WHEN NEW.sequence != 1 + COALESCE((SELECT MAX(sequence) FROM research_amendments WHERE experiment_id=NEW.experiment_id),0)
OR NEW.parent_effective_digest != COALESCE((SELECT new_payload_digest FROM research_amendments WHERE experiment_id=NEW.experiment_id ORDER BY sequence DESC LIMIT 1),(SELECT prereg_digest FROM research_experiments WHERE experiment_id=NEW.experiment_id))
BEGIN SELECT RAISE(ABORT,'INVALID_AMENDMENT_LINEAGE'); END;
CREATE TRIGGER research_grant_type BEFORE INSERT ON research_holdout_grants
WHEN (SELECT experiment_type FROM research_experiments WHERE experiment_id=NEW.experiment_id) NOT IN ('CONFIRMATORY','PROMOTION_REVIEW')
OR NEW.effective_prereg_digest != COALESCE((SELECT new_payload_digest FROM research_amendments WHERE experiment_id=NEW.experiment_id ORDER BY sequence DESC LIMIT 1),(SELECT prereg_digest FROM research_experiments WHERE experiment_id=NEW.experiment_id))
BEGIN SELECT RAISE(ABORT,'INVALID_HOLDOUT_GRANT'); END;
