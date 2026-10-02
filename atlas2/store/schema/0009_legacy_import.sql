CREATE TABLE legacy_import_sources (
 source_id TEXT PRIMARY KEY,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('H4_IMPULSE_HISTORY','RECORDED_REPORT')),
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 byte_size INTEGER NOT NULL CHECK(byte_size>=0),
 basename TEXT NOT NULL,
 schema_digest TEXT NOT NULL CHECK(length(schema_digest)=64),
 mapping_json TEXT NOT NULL,
 UNIQUE(source_kind,source_sha256,schema_digest,mapping_json)
) STRICT;

CREATE TABLE legacy_import_rows (
 import_row_id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES legacy_import_sources(source_id),
 source_key TEXT NOT NULL,
 source_row_digest TEXT NOT NULL CHECK(length(source_row_digest)=64),
 actor_kind TEXT NOT NULL CHECK(actor_kind IN ('OWNER','ENGINE')),
 task_id TEXT NOT NULL REFERENCES label_tasks(task_id),
 group_id TEXT NOT NULL REFERENCES label_groups(group_id),
 UNIQUE(source_id,source_key)
) STRICT;

CREATE TRIGGER immut_legacy_import_sources_update BEFORE UPDATE ON legacy_import_sources BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_legacy_import_sources_delete BEFORE DELETE ON legacy_import_sources BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_legacy_import_sources_insert BEFORE INSERT ON legacy_import_sources
WHEN EXISTS(SELECT 1 FROM legacy_import_sources WHERE source_id=NEW.source_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_legacy_import_rows_update BEFORE UPDATE ON legacy_import_rows BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_legacy_import_rows_delete BEFORE DELETE ON legacy_import_rows BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_legacy_import_rows_insert BEFORE INSERT ON legacy_import_rows
WHEN EXISTS(
 SELECT 1 FROM legacy_import_rows
 WHERE import_row_id=NEW.import_row_id
    OR (source_id=NEW.source_id AND source_key=NEW.source_key)
)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
