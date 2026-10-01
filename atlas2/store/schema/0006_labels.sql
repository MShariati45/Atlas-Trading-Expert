CREATE TABLE label_task_seeds (
 seed_id TEXT PRIMARY KEY,
 study_id TEXT NOT NULL,
 instrument_id TEXT NOT NULL,
 timeframe TEXT NOT NULL CHECK(timeframe IN ('M15','H1','H4','D1')),
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 visible_data_cutoff_us INTEGER NOT NULL,
 lookback_bars INTEGER NOT NULL CHECK(lookback_bars>0),
 blind_mode TEXT NOT NULL CHECK(blind_mode IN ('NONE','IDENTITY','IDENTITY_PRICE')),
 repeat_index INTEGER NOT NULL CHECK(repeat_index>=0),
 include_forming_bar INTEGER NOT NULL CHECK(include_forming_bar=0),
 UNIQUE(study_id,instrument_id,timeframe,dataset_id,visible_data_cutoff_us,lookback_bars,blind_mode,repeat_index)
) STRICT;

CREATE TABLE label_tasks (
 task_id TEXT PRIMARY KEY,
 seed_id TEXT NOT NULL REFERENCES label_task_seeds(seed_id),
 transform_json TEXT NOT NULL,
 UNIQUE(seed_id,transform_json)
) STRICT;

CREATE TABLE label_groups (
 group_id TEXT PRIMARY KEY,
 task_id TEXT NOT NULL REFERENCES label_tasks(task_id),
 labeler_id TEXT NOT NULL,
 request_key TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('INTERPRETATIONS','ABSTENTION')),
 label_mode TEXT NOT NULL CHECK(label_mode IN ('OPERATIONAL','RETROSPECTIVE','LEGACY_IMPORT','ENGINE')),
 submitted_at_us INTEGER NOT NULL,
 visible_data_cutoff_us INTEGER NOT NULL,
 operational_available_at_us INTEGER,
 supersedes_group_id TEXT UNIQUE REFERENCES label_groups(group_id),
 revision_reason TEXT,
 abstention_reason TEXT,
 exposure_attestation TEXT NOT NULL,
 system_exposure_flag INTEGER NOT NULL CHECK(system_exposure_flag IN (0,1)),
 taint INTEGER NOT NULL CHECK(taint>=0),
 UNIQUE(task_id,labeler_id,request_key),
 CHECK(submitted_at_us>=visible_data_cutoff_us),
 CHECK((label_mode<>'RETROSPECTIVE') OR ((taint & 1)<>0)),
 CHECK((label_mode<>'LEGACY_IMPORT') OR ((taint & 64)<>0)),
 CHECK(
   (label_mode='OPERATIONAL' AND operational_available_at_us=submitted_at_us)
   OR (label_mode<>'OPERATIONAL' AND operational_available_at_us IS NULL)
 ),
 CHECK(
   (supersedes_group_id IS NULL AND revision_reason IS NULL)
   OR (supersedes_group_id IS NOT NULL AND revision_reason IS NOT NULL)
 ),
 CHECK(
   (kind='ABSTENTION' AND abstention_reason IS NOT NULL)
   OR (kind='INTERPRETATIONS' AND abstention_reason IS NULL)
 )
) STRICT;

CREATE TABLE label_interpretations (
 interpretation_id TEXT PRIMARY KEY,
 group_id TEXT NOT NULL REFERENCES label_groups(group_id),
 rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3),
 probability_ppm INTEGER CHECK(probability_ppm IS NULL OR (probability_ppm>=0 AND probability_ppm<=1000000)),
 trend TEXT NOT NULL CHECK(trend IN ('BULLISH','BEARISH','RANGE','TRANSITION')),
 confidence INTEGER NOT NULL CHECK(confidence BETWEEN 1 AND 5),
 correction_depth_ppm INTEGER CHECK(correction_depth_ppm IS NULL OR correction_depth_ppm>=0),
 correction_class TEXT CHECK(correction_class IS NULL OR correction_class IN ('MINOR','MAJOR','NONE_YET','UNCLASSIFIED_EQUALITY')),
 reason TEXT,
 UNIQUE(group_id,rank)
) STRICT;

CREATE TABLE label_anchors (
 anchor_id TEXT PRIMARY KEY,
 interpretation_id TEXT NOT NULL REFERENCES label_interpretations(interpretation_id),
 role TEXT NOT NULL CHECK(role IN ('IMPULSE_START','IMPULSE_END','CORRECTION_EXTREME')),
 bar_open_time_us INTEGER,
 side TEXT NOT NULL CHECK(side IN ('HIGH','LOW')),
 price INTEGER NOT NULL,
 confirmation_time_us INTEGER,
 time_status TEXT NOT NULL CHECK(time_status IN ('EXACT_BAR','UNKNOWN_LEGACY','INFERRED_RECONSTRUCTION')),
 UNIQUE(interpretation_id,role),
 CHECK(
   (time_status='UNKNOWN_LEGACY' AND bar_open_time_us IS NULL AND confirmation_time_us IS NULL)
   OR (time_status<>'UNKNOWN_LEGACY' AND bar_open_time_us IS NOT NULL)
 )
) STRICT;

CREATE TABLE label_set_pins (
 pin_id TEXT PRIMARY KEY,
 view_kind TEXT NOT NULL CHECK(view_kind IN ('OPERATIONAL','RESEARCH')),
 group_ids_json TEXT NOT NULL,
 selector_policy_version TEXT NOT NULL,
 taint INTEGER NOT NULL CHECK(taint>=0)
) STRICT;

DROP TRIGGER seal_parent_exists;
CREATE TRIGGER seal_parent_exists BEFORE INSERT ON sys_seals BEGIN
 SELECT CASE
 WHEN NEW.aggregate_kind='run_manifests' AND EXISTS(SELECT 1 FROM run_manifests WHERE manifest_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='run_attempt_starts' AND EXISTS(SELECT 1 FROM run_attempt_starts WHERE attempt_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='data_datasets' AND EXISTS(SELECT 1 FROM data_datasets WHERE dataset_id=NEW.aggregate_id) THEN 1
 WHEN NEW.aggregate_kind='label_groups' AND EXISTS(SELECT 1 FROM label_groups WHERE group_id=NEW.aggregate_id) THEN 1
 ELSE RAISE(ABORT,'UNKNOWN_SEAL_PARENT') END;
END;

CREATE TRIGGER label_group_task_cutoff BEFORE INSERT ON label_groups
WHEN NEW.visible_data_cutoff_us <> (
  SELECT s.visible_data_cutoff_us
  FROM label_tasks t
  JOIN label_task_seeds s ON s.seed_id=t.seed_id
  WHERE t.task_id=NEW.task_id
)
BEGIN SELECT RAISE(ABORT,'LABEL_TASK_CUTOFF_MISMATCH'); END;

CREATE TRIGGER label_group_revision_lineage BEFORE INSERT ON label_groups
WHEN
 (
   NEW.supersedes_group_id IS NULL
   AND EXISTS(
     SELECT 1 FROM label_groups
     WHERE task_id=NEW.task_id AND labeler_id=NEW.labeler_id
   )
 )
 OR
 (
   NEW.supersedes_group_id IS NOT NULL
   AND NOT EXISTS(
     SELECT 1 FROM label_groups p
     WHERE p.group_id=NEW.supersedes_group_id
       AND p.task_id=NEW.task_id
       AND p.labeler_id=NEW.labeler_id
       AND p.submitted_at_us < NEW.submitted_at_us
   )
 )
BEGIN SELECT RAISE(ABORT,'INVALID_LABEL_REVISION_LINEAGE'); END;

CREATE TRIGGER label_interpretations_require_kind BEFORE INSERT ON label_interpretations
WHEN (SELECT kind FROM label_groups WHERE group_id=NEW.group_id) <> 'INTERPRETATIONS'
BEGIN SELECT RAISE(ABORT,'INTERPRETATION_ON_ABSTENTION'); END;

CREATE TRIGGER sealed_label_group_interpretations BEFORE INSERT ON label_interpretations
WHEN EXISTS(
 SELECT 1 FROM sys_seals
 WHERE aggregate_kind='label_groups' AND aggregate_id=NEW.group_id
)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;

CREATE TRIGGER sealed_label_group_anchors BEFORE INSERT ON label_anchors
WHEN EXISTS(
 SELECT 1
 FROM label_interpretations i
 JOIN sys_seals s
   ON s.aggregate_kind='label_groups' AND s.aggregate_id=i.group_id
 WHERE i.interpretation_id=NEW.interpretation_id
)
BEGIN SELECT RAISE(ABORT,'SEAL_VIOLATION'); END;

CREATE TRIGGER label_probability_sum BEFORE INSERT ON label_interpretations
WHEN NEW.probability_ppm IS NOT NULL
 AND NEW.probability_ppm + COALESCE(
   (SELECT SUM(probability_ppm) FROM label_interpretations WHERE group_id=NEW.group_id),
   0
 ) > 1000000
BEGIN SELECT RAISE(ABORT,'PROBABILITY_SUM_EXCEEDED'); END;

CREATE TRIGGER label_inferred_anchor_requires_taint BEFORE INSERT ON label_anchors
WHEN NEW.time_status='INFERRED_RECONSTRUCTION'
 AND (
   SELECT (g.taint & 64)=0
   FROM label_interpretations i
   JOIN label_groups g ON g.group_id=i.group_id
   WHERE i.interpretation_id=NEW.interpretation_id
 )
BEGIN SELECT RAISE(ABORT,'INFERRED_ANCHOR_REQUIRES_TAINT'); END;

CREATE TRIGGER label_anchor_within_cutoff BEFORE INSERT ON label_anchors
WHEN NEW.time_status<>'UNKNOWN_LEGACY'
 AND (
   NEW.bar_open_time_us + (
     SELECT CASE s.timeframe
       WHEN 'M15' THEN 900000000
       WHEN 'H1' THEN 3600000000
       WHEN 'H4' THEN 14400000000
       WHEN 'D1' THEN 86400000000
     END
     FROM label_interpretations i
     JOIN label_groups g ON g.group_id=i.group_id
     JOIN label_tasks t ON t.task_id=g.task_id
     JOIN label_task_seeds s ON s.seed_id=t.seed_id
     WHERE i.interpretation_id=NEW.interpretation_id
   ) > (
     SELECT g.visible_data_cutoff_us
     FROM label_interpretations i
     JOIN label_groups g ON g.group_id=i.group_id
     WHERE i.interpretation_id=NEW.interpretation_id
   )
   OR (
     NEW.confirmation_time_us IS NOT NULL
     AND (
       NEW.confirmation_time_us < NEW.bar_open_time_us + (
         SELECT CASE s.timeframe
           WHEN 'M15' THEN 900000000
           WHEN 'H1' THEN 3600000000
           WHEN 'H4' THEN 14400000000
           WHEN 'D1' THEN 86400000000
         END
         FROM label_interpretations i
         JOIN label_groups g ON g.group_id=i.group_id
         JOIN label_tasks t ON t.task_id=g.task_id
         JOIN label_task_seeds s ON s.seed_id=t.seed_id
         WHERE i.interpretation_id=NEW.interpretation_id
       )
       OR NEW.confirmation_time_us > (
         SELECT g.visible_data_cutoff_us
         FROM label_interpretations i
         JOIN label_groups g ON g.group_id=i.group_id
         WHERE i.interpretation_id=NEW.interpretation_id
       )
     )
   )
 )
BEGIN SELECT RAISE(ABORT,'INVALID_ANCHOR_TIME'); END;

CREATE TRIGGER label_group_seal_valid BEFORE INSERT ON sys_seals
WHEN NEW.aggregate_kind='label_groups'
 AND (
   (
     (SELECT kind FROM label_groups WHERE group_id=NEW.aggregate_id)='INTERPRETATIONS'
     AND (
       (SELECT COUNT(*) FROM label_interpretations WHERE group_id=NEW.aggregate_id) < 1
       OR (SELECT COUNT(*) FROM label_interpretations WHERE group_id=NEW.aggregate_id) > 3
     )
   )
   OR
   (
     (SELECT kind FROM label_groups WHERE group_id=NEW.aggregate_id)='ABSTENTION'
     AND (SELECT COUNT(*) FROM label_interpretations WHERE group_id=NEW.aggregate_id) <> 0
   )
 )
BEGIN SELECT RAISE(ABORT,'INVALID_LABEL_GROUP_SEAL'); END;

CREATE TRIGGER immut_label_task_seeds_update BEFORE UPDATE ON label_task_seeds BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_task_seeds_delete BEFORE DELETE ON label_task_seeds BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_task_seeds_insert BEFORE INSERT ON label_task_seeds
WHEN EXISTS(
 SELECT 1 FROM label_task_seeds
 WHERE seed_id=NEW.seed_id
    OR (
      study_id=NEW.study_id AND instrument_id=NEW.instrument_id
      AND timeframe=NEW.timeframe AND dataset_id=NEW.dataset_id
      AND visible_data_cutoff_us=NEW.visible_data_cutoff_us
      AND lookback_bars=NEW.lookback_bars AND blind_mode=NEW.blind_mode
      AND repeat_index=NEW.repeat_index
    )
)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_label_tasks_update BEFORE UPDATE ON label_tasks BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_tasks_delete BEFORE DELETE ON label_tasks BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_tasks_insert BEFORE INSERT ON label_tasks
WHEN EXISTS(
 SELECT 1 FROM label_tasks
 WHERE task_id=NEW.task_id
    OR (seed_id=NEW.seed_id AND transform_json=NEW.transform_json)
)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_label_groups_update BEFORE UPDATE ON label_groups BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_groups_delete BEFORE DELETE ON label_groups BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_groups_insert BEFORE INSERT ON label_groups
WHEN EXISTS(
 SELECT 1 FROM label_groups
 WHERE group_id=NEW.group_id
    OR (task_id=NEW.task_id AND labeler_id=NEW.labeler_id AND request_key=NEW.request_key)
    OR (
      NEW.supersedes_group_id IS NOT NULL
      AND supersedes_group_id=NEW.supersedes_group_id
    )
)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_label_interpretations_update BEFORE UPDATE ON label_interpretations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_interpretations_delete BEFORE DELETE ON label_interpretations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_interpretations_insert BEFORE INSERT ON label_interpretations
WHEN EXISTS(SELECT 1 FROM label_interpretations WHERE interpretation_id=NEW.interpretation_id OR (group_id=NEW.group_id AND rank=NEW.rank))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_label_anchors_update BEFORE UPDATE ON label_anchors BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_anchors_delete BEFORE DELETE ON label_anchors BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_anchors_insert BEFORE INSERT ON label_anchors
WHEN EXISTS(SELECT 1 FROM label_anchors WHERE anchor_id=NEW.anchor_id OR (interpretation_id=NEW.interpretation_id AND role=NEW.role))
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_label_set_pins_update BEFORE UPDATE ON label_set_pins BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_set_pins_delete BEFORE DELETE ON label_set_pins BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_label_set_pins_insert BEFORE INSERT ON label_set_pins
WHEN EXISTS(SELECT 1 FROM label_set_pins WHERE pin_id=NEW.pin_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
