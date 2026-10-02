CREATE TABLE market_snapshots (
 snapshot_id TEXT PRIMARY KEY,
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 instrument_id TEXT NOT NULL,
 as_of_us INTEGER NOT NULL,
 view_class TEXT NOT NULL CHECK(view_class IN ('PIT','NON_PIT')),
 mode TEXT NOT NULL CHECK(mode IN ('REPLAY','FORWARD')),
 windows_json TEXT NOT NULL,
 visible_fact_digest TEXT NOT NULL CHECK(length(visible_fact_digest)=64),
 taint INTEGER NOT NULL CHECK(taint>=0)
) STRICT;

CREATE TABLE strategy_versions (
 strategy_version_id TEXT PRIMARY KEY,
 strategy_key TEXT NOT NULL,
 version TEXT NOT NULL,
 gate_roles_json TEXT NOT NULL,
 plan_json TEXT NOT NULL,
 UNIQUE(strategy_key,version)
) STRICT;

CREATE TABLE capture_units (
 capture_unit_id TEXT PRIMARY KEY,
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 instrument_id TEXT NOT NULL,
 decision_time_us INTEGER NOT NULL,
 snapshot_id TEXT NOT NULL REFERENCES market_snapshots(snapshot_id),
 candidate_ids_json TEXT NOT NULL,
 semantic_capture_digest TEXT NOT NULL CHECK(length(semantic_capture_digest)=64),
 UNIQUE(dataset_id,instrument_id,decision_time_us,snapshot_id,semantic_capture_digest)
) STRICT;

CREATE TABLE capture_unit_members (
 capture_unit_id TEXT NOT NULL REFERENCES capture_units(capture_unit_id),
 member_kind TEXT NOT NULL CHECK(member_kind IN ('SNAPSHOT','INVOCATION','INVOCATION_END','RECEIPT','CANDIDATE')),
 member_id TEXT NOT NULL,
 content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
 PRIMARY KEY(capture_unit_id,member_kind,member_id)
) STRICT;

CREATE TABLE evaluation_contexts (
 ctx_id TEXT PRIMARY KEY,
 capture_unit_id TEXT NOT NULL REFERENCES capture_units(capture_unit_id),
 label_pin_id TEXT REFERENCES label_set_pins(pin_id),
 macro_view_class TEXT NOT NULL CHECK(macro_view_class IN ('PIT','NON_PIT')),
 mode TEXT NOT NULL CHECK(mode IN ('REPLAY','FORWARD')),
 taint INTEGER NOT NULL CHECK(taint>=0),
 UNIQUE(capture_unit_id,label_pin_id,macro_view_class,mode)
) STRICT;

CREATE TABLE candidate_relations (
 relation_id TEXT PRIMARY KEY,
 ctx_id TEXT NOT NULL REFERENCES evaluation_contexts(ctx_id),
 relation_kind TEXT NOT NULL CHECK(relation_kind IN ('SAME_EVENT_DUPLICATE','CONFIRMS','PRIMARY_OF')),
 evaluator_version_id TEXT NOT NULL,
 primary_candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
 other_candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
 taint INTEGER NOT NULL CHECK(taint>=0),
 UNIQUE(ctx_id,relation_kind,evaluator_version_id,primary_candidate_id,other_candidate_id),
 CHECK(primary_candidate_id<>other_candidate_id)
) STRICT;

CREATE TABLE gate_results (
 gate_id TEXT PRIMARY KEY,
 ctx_id TEXT NOT NULL REFERENCES evaluation_contexts(ctx_id),
 candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
 gate_kind TEXT NOT NULL CHECK(gate_kind IN ('DATA_QUALITY','M15_COORDINATION','H4_CONTEXT','H1_CONTEXT','CORRECTION_LOCATION','SESSION_DAY','NEWS_RISK','SPREAD_COST')),
 evaluator_version_id TEXT NOT NULL,
 input_refs_json TEXT NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('PASS','FAIL','WAIT','ABSTAIN','NOT_APPLICABLE','NOT_EVALUABLE','ERROR')),
 reason_code TEXT,
 error_code TEXT,
 measurements_json TEXT NOT NULL,
 taint INTEGER NOT NULL CHECK(taint>=0),
 UNIQUE(ctx_id,candidate_id,gate_kind,evaluator_version_id,input_refs_json),
 CHECK(outcome<>'ERROR' OR error_code IS NOT NULL)
) STRICT;

CREATE TABLE arm_results (
 arm_id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
 strategy_version_id TEXT NOT NULL REFERENCES strategy_versions(strategy_version_id),
 ctx_id TEXT NOT NULL REFERENCES evaluation_contexts(ctx_id),
 gate_refs_json TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('ACCEPT','REJECT','ABSTAIN','NOT_ELIGIBLE','ERROR')),
 reason_codes_json TEXT NOT NULL,
 plan_json TEXT NOT NULL,
 taint INTEGER NOT NULL CHECK(taint>=0),
 UNIQUE(candidate_id,strategy_version_id,ctx_id)
) STRICT;

CREATE TABLE evaluation_unit_members (
 ctx_id TEXT NOT NULL REFERENCES evaluation_contexts(ctx_id),
 member_kind TEXT NOT NULL CHECK(member_kind IN ('RELATION','GATE','ARM')),
 member_id TEXT NOT NULL,
 content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
 PRIMARY KEY(ctx_id,member_kind,member_id)
) STRICT;

CREATE TABLE outcome_batches (
 batch_id TEXT PRIMARY KEY,
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 fixture_name TEXT NOT NULL,
 UNIQUE(dataset_id,fixture_name)
) STRICT;

CREATE TABLE outcome_attachments (
 outcome_id TEXT PRIMARY KEY,
 batch_id TEXT NOT NULL REFERENCES outcome_batches(batch_id),
 subject_kind TEXT NOT NULL CHECK(subject_kind IN ('ARM','CANDIDATE_REFERENCE')),
 subject_ref TEXT NOT NULL,
 reference_plan_id TEXT,
 resolver_version_id TEXT NOT NULL,
 cost_model_version_id TEXT NOT NULL,
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 status TEXT NOT NULL CHECK(status IN ('RESOLVED','AMBIGUOUS','NOT_FILLED','DATA_END','INVALID_PLAN','UNMEASURABLE')),
 entry_time_us INTEGER,
 r_low_micro INTEGER,
 r_high_micro INTEGER,
 exit_reason TEXT,
 be_triggered INTEGER CHECK(be_triggered IS NULL OR be_triggered IN (0,1)),
 mae_micro INTEGER,
 mfe_micro INTEGER,
 path_resolution TEXT CHECK(path_resolution IS NULL OR path_resolution IN ('M15_OHLC','M1_OHLC','TICK','FIXTURE')),
 taint INTEGER NOT NULL CHECK(taint>=0),
 CHECK(r_low_micro IS NULL OR r_high_micro IS NULL OR r_low_micro<=r_high_micro),
 CHECK((subject_kind='ARM' AND reference_plan_id IS NULL) OR (subject_kind='CANDIDATE_REFERENCE' AND reference_plan_id IS NOT NULL))
) STRICT;

CREATE TABLE outcome_batch_members (
 batch_id TEXT NOT NULL REFERENCES outcome_batches(batch_id),
 outcome_id TEXT NOT NULL REFERENCES outcome_attachments(outcome_id),
 content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
 PRIMARY KEY(batch_id,outcome_id)
) STRICT;

CREATE TABLE run_aggregate_refs (
 manifest_id TEXT NOT NULL REFERENCES run_manifests(manifest_id),
 aggregate_kind TEXT NOT NULL CHECK(aggregate_kind IN ('capture_units','evaluation_contexts','outcome_batches')),
 aggregate_id TEXT NOT NULL,
 PRIMARY KEY(manifest_id,aggregate_kind,aggregate_id)
) STRICT;

CREATE TRIGGER run_aggregate_requires_seal BEFORE INSERT ON run_aggregate_refs
WHEN NOT EXISTS(
 SELECT 1 FROM sys_seals
 WHERE aggregate_kind=NEW.aggregate_kind AND aggregate_id=NEW.aggregate_id
)
BEGIN SELECT RAISE(ABORT,'UNSEALED_RUN_AGGREGATE'); END;

DROP TRIGGER seal_parent_exists;
CREATE TRIGGER seal_parent_exists BEFORE INSERT ON sys_seals BEGIN
 SELECT CASE
 WHEN NEW.aggregate_kind='run_manifests' AND EXISTS(SELECT 1 FROM run_manifests WHERE manifest_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='run_attempt_starts' AND EXISTS(SELECT 1 FROM run_attempt_starts WHERE attempt_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='data_datasets' AND EXISTS(SELECT 1 FROM data_datasets WHERE dataset_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='label_groups' AND EXISTS(SELECT 1 FROM label_groups WHERE group_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='capture_units' AND EXISTS(SELECT 1 FROM capture_units WHERE capture_unit_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='evaluation_contexts' AND EXISTS(SELECT 1 FROM evaluation_contexts WHERE ctx_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='outcome_batches' AND EXISTS(SELECT 1 FROM outcome_batches WHERE batch_id=NEW.aggregate_id) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_SEAL_PARENT') END;
END;

CREATE TRIGGER capture_member_reference BEFORE INSERT ON capture_unit_members BEGIN
 SELECT CASE
 WHEN NEW.member_kind='SNAPSHOT' AND EXISTS(SELECT 1 FROM market_snapshots WHERE snapshot_id=NEW.member_id) THEN 1
 WHEN NEW.member_kind='INVOCATION' AND EXISTS(SELECT 1 FROM detector_invocations WHERE invocation_id=NEW.member_id) THEN 1
 WHEN NEW.member_kind='INVOCATION_END' AND EXISTS(SELECT 1 FROM detector_invocation_ends WHERE invocation_id=NEW.member_id) THEN 1
 WHEN NEW.member_kind='RECEIPT' AND EXISTS(SELECT 1 FROM raw_detection_receipts WHERE receipt_id=NEW.member_id) THEN 1
 WHEN NEW.member_kind='CANDIDATE' AND EXISTS(SELECT 1 FROM candidates WHERE candidate_id=NEW.member_id) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_CAPTURE_MEMBER') END;
END;

CREATE TRIGGER capture_candidate_matches_unit BEFORE INSERT ON capture_unit_members
WHEN NEW.member_kind='CANDIDATE' AND NOT EXISTS(
 SELECT 1
 FROM capture_units u
 JOIN candidates c ON c.candidate_id=NEW.member_id
 JOIN raw_detection_receipts r ON r.receipt_id=c.receipt_id
 JOIN detector_invocations i ON i.invocation_id=r.invocation_id
 WHERE u.capture_unit_id=NEW.capture_unit_id
   AND i.dataset_id=u.dataset_id
   AND c.instrument_id=u.instrument_id
   AND c.available_at_us<=u.decision_time_us
)
BEGIN SELECT RAISE(ABORT,'CAPTURE_CANDIDATE_MISMATCH'); END;

CREATE TRIGGER sealed_capture_member BEFORE INSERT ON capture_unit_members
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='capture_units' AND aggregate_id=NEW.capture_unit_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;

CREATE TRIGGER capture_seal_complete BEFORE INSERT ON sys_seals
WHEN NEW.aggregate_kind='capture_units' AND (
 (SELECT count(*) FROM capture_unit_members
  WHERE capture_unit_id=NEW.aggregate_id AND member_kind='SNAPSHOT') <> 1
 OR NOT EXISTS(
  SELECT 1 FROM capture_units u
  JOIN capture_unit_members m
    ON m.capture_unit_id=u.capture_unit_id
   AND m.member_kind='SNAPSHOT'
   AND m.member_id=u.snapshot_id
  WHERE u.capture_unit_id=NEW.aggregate_id
 )
 OR (
  SELECT '[' || COALESCE(group_concat(quoted, ','), '') || ']'
  FROM (
   SELECT '"' || member_id || '"' AS quoted
   FROM capture_unit_members
   WHERE capture_unit_id=NEW.aggregate_id AND member_kind='CANDIDATE'
   ORDER BY member_id
  )
 ) <> (
  SELECT candidate_ids_json FROM capture_units WHERE capture_unit_id=NEW.aggregate_id
 )
 OR EXISTS(
  SELECT 1 FROM capture_unit_members inv
  WHERE inv.capture_unit_id=NEW.aggregate_id AND inv.member_kind='INVOCATION'
    AND NOT EXISTS(
      SELECT 1 FROM capture_unit_members e
      WHERE e.capture_unit_id=inv.capture_unit_id
        AND e.member_kind='INVOCATION_END'
        AND e.member_id=inv.member_id
    )
 )
 OR EXISTS(
  SELECT 1 FROM capture_unit_members e
  WHERE e.capture_unit_id=NEW.aggregate_id AND e.member_kind='INVOCATION_END'
    AND NOT EXISTS(
      SELECT 1 FROM capture_unit_members inv
      WHERE inv.capture_unit_id=e.capture_unit_id
        AND inv.member_kind='INVOCATION'
        AND inv.member_id=e.member_id
    )
 )
 OR EXISTS(
  SELECT 1
  FROM capture_unit_members rm
  JOIN raw_detection_receipts r ON r.receipt_id=rm.member_id
  WHERE rm.capture_unit_id=NEW.aggregate_id AND rm.member_kind='RECEIPT'
    AND NOT EXISTS(
      SELECT 1 FROM capture_unit_members inv
      WHERE inv.capture_unit_id=rm.capture_unit_id
        AND inv.member_kind='INVOCATION'
        AND inv.member_id=r.invocation_id
    )
 )
 OR EXISTS(
  SELECT 1
  FROM capture_unit_members cm
  JOIN candidates c ON c.candidate_id=cm.member_id
  WHERE cm.capture_unit_id=NEW.aggregate_id AND cm.member_kind='CANDIDATE'
    AND NOT EXISTS(
      SELECT 1 FROM capture_unit_members rm
      WHERE rm.capture_unit_id=cm.capture_unit_id
        AND rm.member_kind='RECEIPT'
        AND rm.member_id=c.receipt_id
    )
 )
 OR EXISTS(
  SELECT 1
  FROM capture_unit_members inv
  JOIN raw_detection_receipts r ON r.invocation_id=inv.member_id
  WHERE inv.capture_unit_id=NEW.aggregate_id AND inv.member_kind='INVOCATION'
    AND NOT EXISTS(
      SELECT 1 FROM capture_unit_members rm
      WHERE rm.capture_unit_id=inv.capture_unit_id
        AND rm.member_kind='RECEIPT'
        AND rm.member_id=r.receipt_id
    )
 )
 OR EXISTS(
  SELECT 1
  FROM capture_unit_members rm
  JOIN candidates c ON c.receipt_id=rm.member_id
  WHERE rm.capture_unit_id=NEW.aggregate_id AND rm.member_kind='RECEIPT'
    AND NOT EXISTS(
      SELECT 1 FROM capture_unit_members cm
      WHERE cm.capture_unit_id=rm.capture_unit_id
        AND cm.member_kind='CANDIDATE'
        AND cm.member_id=c.candidate_id
    )
 )
)
BEGIN SELECT RAISE(ABORT,'CAPTURE_UNIT_INCOMPLETE'); END;

CREATE TRIGGER context_requires_sealed_capture BEFORE INSERT ON evaluation_contexts
WHEN NOT EXISTS(
 SELECT 1 FROM sys_seals
 WHERE aggregate_kind='capture_units' AND aggregate_id=NEW.capture_unit_id
)
BEGIN SELECT RAISE(ABORT,'UNSEALED_CAPTURE_UNIT'); END;

CREATE TRIGGER context_mode_matches_snapshot BEFORE INSERT ON evaluation_contexts
WHEN NOT EXISTS(
 SELECT 1 FROM capture_units u
 JOIN market_snapshots s ON s.snapshot_id=u.snapshot_id
 WHERE u.capture_unit_id=NEW.capture_unit_id AND s.mode=NEW.mode
)
BEGIN SELECT RAISE(ABORT,'CONTEXT_SNAPSHOT_MODE_MISMATCH'); END;

CREATE TRIGGER relation_candidates_in_context BEFORE INSERT ON candidate_relations
WHEN NOT EXISTS(
 SELECT 1 FROM evaluation_contexts x
 JOIN capture_unit_members a ON a.capture_unit_id=x.capture_unit_id AND a.member_kind='CANDIDATE' AND a.member_id=NEW.primary_candidate_id
 JOIN capture_unit_members b ON b.capture_unit_id=x.capture_unit_id AND b.member_kind='CANDIDATE' AND b.member_id=NEW.other_candidate_id
 WHERE x.ctx_id=NEW.ctx_id
)
BEGIN SELECT RAISE(ABORT,'RELATION_OUTSIDE_CONTEXT'); END;

CREATE TRIGGER gate_candidate_in_context BEFORE INSERT ON gate_results
WHEN NOT EXISTS(
 SELECT 1 FROM evaluation_contexts x
 JOIN capture_unit_members m ON m.capture_unit_id=x.capture_unit_id AND m.member_kind='CANDIDATE' AND m.member_id=NEW.candidate_id
 WHERE x.ctx_id=NEW.ctx_id
)
BEGIN SELECT RAISE(ABORT,'GATE_OUTSIDE_CONTEXT'); END;

CREATE TRIGGER arm_candidate_in_context BEFORE INSERT ON arm_results
WHEN NOT EXISTS(
 SELECT 1 FROM evaluation_contexts x
 JOIN capture_unit_members m ON m.capture_unit_id=x.capture_unit_id AND m.member_kind='CANDIDATE' AND m.member_id=NEW.candidate_id
 WHERE x.ctx_id=NEW.ctx_id
)
BEGIN SELECT RAISE(ABORT,'ARM_OUTSIDE_CONTEXT'); END;

CREATE TRIGGER sealed_relation BEFORE INSERT ON candidate_relations
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=NEW.ctx_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;
CREATE TRIGGER sealed_gate BEFORE INSERT ON gate_results
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=NEW.ctx_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;
CREATE TRIGGER sealed_arm BEFORE INSERT ON arm_results
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=NEW.ctx_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;
CREATE TRIGGER sealed_evaluation_member BEFORE INSERT ON evaluation_unit_members
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='evaluation_contexts' AND aggregate_id=NEW.ctx_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;

CREATE TRIGGER evaluation_member_reference BEFORE INSERT ON evaluation_unit_members BEGIN
 SELECT CASE
 WHEN NEW.member_kind='RELATION' AND EXISTS(SELECT 1 FROM candidate_relations WHERE relation_id=NEW.member_id AND ctx_id=NEW.ctx_id) THEN 1
 WHEN NEW.member_kind='GATE' AND EXISTS(SELECT 1 FROM gate_results WHERE gate_id=NEW.member_id AND ctx_id=NEW.ctx_id) THEN 1
 WHEN NEW.member_kind='ARM' AND EXISTS(SELECT 1 FROM arm_results WHERE arm_id=NEW.member_id AND ctx_id=NEW.ctx_id) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_EVALUATION_MEMBER') END;
END;

CREATE TRIGGER evaluation_seal_complete BEFORE INSERT ON sys_seals
WHEN NEW.aggregate_kind='evaluation_contexts' AND (
 EXISTS(
  SELECT 1 FROM evaluation_contexts x
  JOIN capture_unit_members c ON c.capture_unit_id=x.capture_unit_id AND c.member_kind='CANDIDATE'
  WHERE x.ctx_id=NEW.aggregate_id
    AND NOT EXISTS(SELECT 1 FROM arm_results a WHERE a.ctx_id=x.ctx_id AND a.candidate_id=c.member_id)
 )
 OR EXISTS(
  SELECT 1 FROM candidate_relations r
  WHERE r.ctx_id=NEW.aggregate_id
    AND NOT EXISTS(SELECT 1 FROM evaluation_unit_members m WHERE m.ctx_id=NEW.aggregate_id AND m.member_kind='RELATION' AND m.member_id=r.relation_id)
 )
 OR EXISTS(
  SELECT 1 FROM gate_results g
  WHERE g.ctx_id=NEW.aggregate_id
    AND NOT EXISTS(SELECT 1 FROM evaluation_unit_members m WHERE m.ctx_id=NEW.aggregate_id AND m.member_kind='GATE' AND m.member_id=g.gate_id)
 )
 OR EXISTS(
  SELECT 1 FROM arm_results a
  WHERE a.ctx_id=NEW.aggregate_id
    AND NOT EXISTS(SELECT 1 FROM evaluation_unit_members m WHERE m.ctx_id=NEW.aggregate_id AND m.member_kind='ARM' AND m.member_id=a.arm_id)
 )
)
BEGIN SELECT RAISE(ABORT,'EVALUATION_UNIT_INCOMPLETE'); END;

CREATE TRIGGER outcome_subject_reference BEFORE INSERT ON outcome_attachments BEGIN
 SELECT CASE
 WHEN NEW.subject_kind='ARM' AND EXISTS(SELECT 1 FROM arm_results WHERE arm_id=NEW.subject_ref) THEN 1
 WHEN NEW.subject_kind='CANDIDATE_REFERENCE' AND EXISTS(SELECT 1 FROM candidates WHERE candidate_id=NEW.subject_ref) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_OUTCOME_SUBJECT') END;
END;

CREATE TRIGGER fixture_outcome_requires_synthetic_taint BEFORE INSERT ON outcome_attachments
WHEN NEW.path_resolution='FIXTURE' AND (NEW.taint & 16)=0
BEGIN SELECT RAISE(ABORT,'FIXTURE_REQUIRES_SYNTHETIC_TAINT'); END;

CREATE TRIGGER sealed_outcome_attachment BEFORE INSERT ON outcome_attachments
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='outcome_batches' AND aggregate_id=NEW.batch_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;
CREATE TRIGGER outcome_member_reference BEFORE INSERT ON outcome_batch_members
WHEN NOT EXISTS(
 SELECT 1 FROM outcome_attachments
 WHERE outcome_id=NEW.outcome_id AND batch_id=NEW.batch_id
)
BEGIN SELECT RAISE(ABORT,'OUTCOME_MEMBER_BATCH_MISMATCH'); END;

CREATE TRIGGER sealed_outcome_member BEFORE INSERT ON outcome_batch_members
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='outcome_batches' AND aggregate_id=NEW.batch_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;

CREATE TRIGGER outcome_seal_complete BEFORE INSERT ON sys_seals
WHEN NEW.aggregate_kind='outcome_batches' AND EXISTS(
 SELECT 1 FROM outcome_attachments o
 WHERE o.batch_id=NEW.aggregate_id
   AND NOT EXISTS(SELECT 1 FROM outcome_batch_members m WHERE m.batch_id=NEW.aggregate_id AND m.outcome_id=o.outcome_id)
)
BEGIN SELECT RAISE(ABORT,'OUTCOME_BATCH_INCOMPLETE'); END;

CREATE TRIGGER immut_market_snapshots_update BEFORE UPDATE ON market_snapshots BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_market_snapshots_delete BEFORE DELETE ON market_snapshots BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_market_snapshots_insert BEFORE INSERT ON market_snapshots WHEN EXISTS(SELECT 1 FROM market_snapshots WHERE snapshot_id=NEW.snapshot_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_strategy_versions_update BEFORE UPDATE ON strategy_versions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_strategy_versions_delete BEFORE DELETE ON strategy_versions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_strategy_versions_insert BEFORE INSERT ON strategy_versions WHEN EXISTS(SELECT 1 FROM strategy_versions WHERE strategy_version_id=NEW.strategy_version_id OR (strategy_key=NEW.strategy_key AND version=NEW.version)) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_capture_units_update BEFORE UPDATE ON capture_units BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_capture_units_delete BEFORE DELETE ON capture_units BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_capture_units_insert BEFORE INSERT ON capture_units WHEN EXISTS(SELECT 1 FROM capture_units WHERE capture_unit_id=NEW.capture_unit_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_capture_members_update BEFORE UPDATE ON capture_unit_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_capture_members_delete BEFORE DELETE ON capture_unit_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_capture_members_insert BEFORE INSERT ON capture_unit_members WHEN EXISTS(SELECT 1 FROM capture_unit_members WHERE capture_unit_id=NEW.capture_unit_id AND member_kind=NEW.member_kind AND member_id=NEW.member_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_evaluation_contexts_update BEFORE UPDATE ON evaluation_contexts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_evaluation_contexts_delete BEFORE DELETE ON evaluation_contexts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_evaluation_contexts_insert BEFORE INSERT ON evaluation_contexts WHEN EXISTS(SELECT 1 FROM evaluation_contexts WHERE ctx_id=NEW.ctx_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_candidate_relations_update BEFORE UPDATE ON candidate_relations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_candidate_relations_delete BEFORE DELETE ON candidate_relations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_candidate_relations_insert BEFORE INSERT ON candidate_relations WHEN EXISTS(SELECT 1 FROM candidate_relations WHERE relation_id=NEW.relation_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_gate_results_update BEFORE UPDATE ON gate_results BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_gate_results_delete BEFORE DELETE ON gate_results BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_gate_results_insert BEFORE INSERT ON gate_results WHEN EXISTS(SELECT 1 FROM gate_results WHERE gate_id=NEW.gate_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_arm_results_update BEFORE UPDATE ON arm_results BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_arm_results_delete BEFORE DELETE ON arm_results BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_arm_results_insert BEFORE INSERT ON arm_results WHEN EXISTS(SELECT 1 FROM arm_results WHERE arm_id=NEW.arm_id OR (candidate_id=NEW.candidate_id AND strategy_version_id=NEW.strategy_version_id AND ctx_id=NEW.ctx_id)) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_evaluation_members_update BEFORE UPDATE ON evaluation_unit_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_evaluation_members_delete BEFORE DELETE ON evaluation_unit_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_evaluation_members_insert BEFORE INSERT ON evaluation_unit_members WHEN EXISTS(SELECT 1 FROM evaluation_unit_members WHERE ctx_id=NEW.ctx_id AND member_kind=NEW.member_kind AND member_id=NEW.member_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_outcome_batches_update BEFORE UPDATE ON outcome_batches BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_batches_delete BEFORE DELETE ON outcome_batches BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_batches_insert BEFORE INSERT ON outcome_batches WHEN EXISTS(SELECT 1 FROM outcome_batches WHERE batch_id=NEW.batch_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_attachments_update BEFORE UPDATE ON outcome_attachments BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_attachments_delete BEFORE DELETE ON outcome_attachments BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_attachments_insert BEFORE INSERT ON outcome_attachments WHEN EXISTS(SELECT 1 FROM outcome_attachments WHERE outcome_id=NEW.outcome_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_members_update BEFORE UPDATE ON outcome_batch_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_members_delete BEFORE DELETE ON outcome_batch_members BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_outcome_members_insert BEFORE INSERT ON outcome_batch_members WHEN EXISTS(SELECT 1 FROM outcome_batch_members WHERE batch_id=NEW.batch_id AND outcome_id=NEW.outcome_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_run_aggregate_refs_update BEFORE UPDATE ON run_aggregate_refs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_run_aggregate_refs_delete BEFORE DELETE ON run_aggregate_refs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_run_aggregate_refs_insert BEFORE INSERT ON run_aggregate_refs
WHEN EXISTS(SELECT 1 FROM run_aggregate_refs WHERE manifest_id=NEW.manifest_id AND aggregate_kind=NEW.aggregate_kind AND aggregate_id=NEW.aggregate_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
