CREATE TABLE sys_hardware_baselines (
 baseline_id TEXT PRIMARY KEY,
 captured_at_us INTEGER NOT NULL,
 content_json TEXT NOT NULL
) STRICT;

CREATE TRIGGER immut_sys_hardware_baselines_update BEFORE UPDATE ON sys_hardware_baselines BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_sys_hardware_baselines_delete BEFORE DELETE ON sys_hardware_baselines BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_sys_hardware_baselines_insert BEFORE INSERT ON sys_hardware_baselines
WHEN EXISTS(SELECT 1 FROM sys_hardware_baselines WHERE baseline_id=NEW.baseline_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
