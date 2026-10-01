CREATE TRIGGER immut_sys_schema_migrations_insert BEFORE INSERT ON sys_schema_migrations
WHEN EXISTS(SELECT 1 FROM sys_schema_migrations WHERE version=NEW.version OR filename=NEW.filename)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_sys_request_keys_insert BEFORE INSERT ON sys_request_keys
WHEN EXISTS(SELECT 1 FROM sys_request_keys WHERE actor_id=NEW.actor_id AND action_kind=NEW.action_kind AND client_key=NEW.client_key)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_sys_recovery_epochs_insert BEFORE INSERT ON sys_recovery_epochs
WHEN EXISTS(SELECT 1 FROM sys_recovery_epochs WHERE epoch=NEW.epoch)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_sys_audit_insert BEFORE INSERT ON sys_audit
WHEN EXISTS(SELECT 1 FROM sys_audit WHERE seq=NEW.seq)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_sys_seals_insert BEFORE INSERT ON sys_seals
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind=NEW.aggregate_kind AND aggregate_id=NEW.aggregate_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_run_manifests_insert BEFORE INSERT ON run_manifests
WHEN EXISTS(SELECT 1 FROM run_manifests WHERE manifest_id=NEW.manifest_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_run_attempt_starts_insert BEFORE INSERT ON run_attempt_starts
WHEN EXISTS(SELECT 1 FROM run_attempt_starts WHERE attempt_id=NEW.attempt_id OR (manifest_id=NEW.manifest_id AND recovery_epoch=NEW.recovery_epoch AND attempt_no=NEW.attempt_no))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_run_attempt_ends_insert BEFORE INSERT ON run_attempt_ends
WHEN EXISTS(SELECT 1 FROM run_attempt_ends WHERE attempt_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_raw_blobs_insert BEFORE INSERT ON raw_blobs
WHEN EXISTS(SELECT 1 FROM raw_blobs WHERE blob_sha256=NEW.blob_sha256)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_source_observations_insert BEFORE INSERT ON source_observations
WHEN EXISTS(SELECT 1 FROM source_observations WHERE obs_id=NEW.obs_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
