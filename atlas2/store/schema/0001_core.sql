PRAGMA application_id = 0x41543250;

CREATE TABLE IF NOT EXISTS sys_schema_migrations (
  version INTEGER PRIMARY KEY,
  filename TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  applied_at_us INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS sys_request_keys (
  actor_id TEXT NOT NULL,
  action_kind TEXT NOT NULL,
  client_key TEXT NOT NULL,
  payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64),
  result_ref TEXT NOT NULL,
  server_time_us INTEGER NOT NULL,
  PRIMARY KEY(actor_id, action_kind, client_key)
) STRICT;

CREATE TABLE IF NOT EXISTS sys_recovery_epochs (
  epoch INTEGER PRIMARY KEY,
  restored_from_manifest_digest TEXT,
  restored_head_seq INTEGER,
  restored_head_hash TEXT,
  external_checkpoint_hash TEXT,
  missing_tail TEXT NOT NULL CHECK(missing_tail IN ('NONE','KNOWN_RANGE','UNKNOWN'))
) STRICT;

CREATE TABLE IF NOT EXISTS sys_audit (
  seq INTEGER PRIMARY KEY,
  recovery_epoch INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  actor_kind TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  occurred_at_us INTEGER NOT NULL,
  subject_table TEXT,
  subject_id TEXT,
  payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  record_hash TEXT NOT NULL CHECK(length(record_hash)=64),
  FOREIGN KEY(recovery_epoch) REFERENCES sys_recovery_epochs(epoch)
) STRICT;

CREATE TABLE IF NOT EXISTS sys_seals (
  aggregate_kind TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  child_set_digest TEXT NOT NULL CHECK(length(child_set_digest)=64),
  PRIMARY KEY(aggregate_kind, aggregate_id)
) STRICT;

CREATE TABLE IF NOT EXISTS run_manifests (
  manifest_id TEXT PRIMARY KEY,
  logical_input_digest TEXT NOT NULL CHECK(length(logical_input_digest)=64),
  holdout_batch_session_id TEXT,
  mode TEXT NOT NULL CHECK(mode IN ('REPLAY','FORWARD')),
  content_json TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS run_attempt_starts (
  attempt_id TEXT PRIMARY KEY,
  manifest_id TEXT NOT NULL,
  recovery_epoch INTEGER NOT NULL,
  attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
  started_at_us INTEGER NOT NULL,
  code_ref_json TEXT NOT NULL,
  UNIQUE(manifest_id, recovery_epoch, attempt_no),
  FOREIGN KEY(manifest_id) REFERENCES run_manifests(manifest_id),
  FOREIGN KEY(recovery_epoch) REFERENCES sys_recovery_epochs(epoch)
) STRICT;

CREATE TABLE IF NOT EXISTS run_attempt_ends (
  attempt_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('COMPLETED','FAILED','ABORTED')),
  replay_digest TEXT,
  failure_code TEXT,
  ended_at_us INTEGER NOT NULL,
  FOREIGN KEY(attempt_id) REFERENCES run_attempt_starts(attempt_id)
) STRICT;

INSERT OR IGNORE INTO sys_recovery_epochs(epoch, restored_from_manifest_digest, restored_head_seq, restored_head_hash, external_checkpoint_hash, missing_tail)
VALUES (1, NULL, NULL, NULL, NULL, 'NONE');

CREATE TRIGGER IF NOT EXISTS immut_sys_request_keys_update BEFORE UPDATE ON sys_request_keys BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_request_keys_delete BEFORE DELETE ON sys_request_keys BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_recovery_epochs_update BEFORE UPDATE ON sys_recovery_epochs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_recovery_epochs_delete BEFORE DELETE ON sys_recovery_epochs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_audit_update BEFORE UPDATE ON sys_audit BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_audit_delete BEFORE DELETE ON sys_audit BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_seals_update BEFORE UPDATE ON sys_seals BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_sys_seals_delete BEFORE DELETE ON sys_seals BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_run_manifests_update BEFORE UPDATE ON run_manifests BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_run_manifests_delete BEFORE DELETE ON run_manifests BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_run_attempt_starts_update BEFORE UPDATE ON run_attempt_starts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_run_attempt_starts_delete BEFORE DELETE ON run_attempt_starts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_run_attempt_ends_update BEFORE UPDATE ON run_attempt_ends BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER IF NOT EXISTS immut_run_attempt_ends_delete BEFORE DELETE ON run_attempt_ends BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
