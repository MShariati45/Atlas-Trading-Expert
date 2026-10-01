CREATE TABLE raw_blobs (
 blob_sha256 TEXT PRIMARY KEY CHECK(length(blob_sha256)=64),
 byte_size INTEGER NOT NULL CHECK(byte_size > 0)
) STRICT;
CREATE TABLE source_observations (
 obs_id TEXT PRIMARY KEY,
 blob_sha256 TEXT NOT NULL REFERENCES raw_blobs(blob_sha256),
 source_id TEXT NOT NULL,
 source_version TEXT NOT NULL,
 acquisition_kind TEXT NOT NULL,
 acquired_at_us INTEGER NOT NULL,
 clock_profile_id TEXT NOT NULL
) STRICT;
CREATE TRIGGER immut_raw_blobs_update BEFORE UPDATE ON raw_blobs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_raw_blobs_delete BEFORE DELETE ON raw_blobs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_source_observations_update BEFORE UPDATE ON source_observations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_source_observations_delete BEFORE DELETE ON source_observations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_migrations_update BEFORE UPDATE ON sys_schema_migrations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_migrations_delete BEFORE DELETE ON sys_schema_migrations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER seal_parent_exists BEFORE INSERT ON sys_seals BEGIN
 SELECT CASE
 WHEN NEW.aggregate_kind='run_manifests' AND EXISTS(SELECT 1 FROM run_manifests WHERE manifest_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='run_attempt_starts' AND EXISTS(SELECT 1 FROM run_attempt_starts WHERE attempt_id=NEW.aggregate_id) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_SEAL_PARENT') END;
END;
CREATE TRIGGER sealed_manifest_children BEFORE INSERT ON run_attempt_starts
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='run_manifests' AND aggregate_id=NEW.manifest_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;
CREATE TRIGGER sealed_attempt_children BEFORE INSERT ON run_attempt_ends
WHEN EXISTS(SELECT 1 FROM sys_seals WHERE aggregate_kind='run_attempt_starts' AND aggregate_id=NEW.attempt_id)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;
