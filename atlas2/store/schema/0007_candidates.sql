CREATE TABLE detector_invocations (
 invocation_id TEXT PRIMARY KEY,
 run_attempt_id TEXT NOT NULL REFERENCES run_attempt_starts(attempt_id),
 dataset_id TEXT NOT NULL REFERENCES data_datasets(dataset_id),
 detector_id TEXT NOT NULL,
 detector_version TEXT NOT NULL,
 instrument_id TEXT NOT NULL,
 timeframe TEXT NOT NULL CHECK(timeframe='M15'),
 as_of_us INTEGER NOT NULL,
 parameters_json TEXT NOT NULL
) STRICT;

CREATE TABLE raw_detection_receipts (
 receipt_id TEXT PRIMARY KEY,
 invocation_id TEXT NOT NULL REFERENCES detector_invocations(invocation_id),
 receipt_index INTEGER NOT NULL CHECK(receipt_index>=1),
 occurrence_key TEXT NOT NULL,
 instrument_id TEXT NOT NULL,
 timeframe TEXT NOT NULL CHECK(timeframe='M15'),
 pattern_family TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
 trigger_time_us INTEGER NOT NULL,
 detected_at_us INTEGER NOT NULL,
 available_at_us INTEGER NOT NULL,
 anchors_json TEXT NOT NULL,
 raw_payload_json TEXT NOT NULL,
 evidence_refs_json TEXT NOT NULL,
 source_detector_id TEXT NOT NULL,
 source_detector_version TEXT NOT NULL,
 taint INTEGER NOT NULL CHECK(taint>=0),
 recorded_at_us INTEGER NOT NULL,
 UNIQUE(invocation_id,receipt_index),
 CHECK(trigger_time_us<=detected_at_us AND detected_at_us<=available_at_us)
) STRICT;
CREATE INDEX raw_detection_occurrence ON raw_detection_receipts(occurrence_key);
CREATE INDEX raw_detection_invocation ON raw_detection_receipts(invocation_id,receipt_index);

CREATE TABLE candidates (
 candidate_id TEXT PRIMARY KEY,
 receipt_id TEXT NOT NULL UNIQUE REFERENCES raw_detection_receipts(receipt_id),
 occurrence_key TEXT NOT NULL,
 instrument_id TEXT NOT NULL,
 timeframe TEXT NOT NULL CHECK(timeframe='M15'),
 pattern_family TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
 trigger_time_us INTEGER NOT NULL,
 detected_at_us INTEGER NOT NULL,
 available_at_us INTEGER NOT NULL,
 entry_reference_price INTEGER,
 structural_invalidation_price INTEGER,
 features_json TEXT NOT NULL,
 confidence_ppm INTEGER CHECK(confidence_ppm IS NULL OR (confidence_ppm>=0 AND confidence_ppm<=1000000)),
 evidence_refs_json TEXT NOT NULL,
 source_detector_id TEXT NOT NULL,
 source_detector_version TEXT NOT NULL,
 taint INTEGER NOT NULL CHECK(taint>=0),
 normalized_at_us INTEGER NOT NULL,
 CHECK(trigger_time_us<=detected_at_us AND detected_at_us<=available_at_us)
) STRICT;
CREATE INDEX candidate_occurrence ON candidates(occurrence_key);

CREATE TABLE detector_invocation_ends (
 invocation_id TEXT PRIMARY KEY REFERENCES detector_invocations(invocation_id),
 status TEXT NOT NULL CHECK(status IN ('COMPLETED','FAILED','ABORTED')),
 receipt_count INTEGER NOT NULL CHECK(receipt_count>=0),
 candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
 error_code TEXT,
 ended_at_us INTEGER NOT NULL,
 CHECK(status<>'COMPLETED' OR receipt_count=candidate_count)
) STRICT;

CREATE TRIGGER detector_receipt_before_end BEFORE INSERT ON raw_detection_receipts
WHEN EXISTS(SELECT 1 FROM detector_invocation_ends WHERE invocation_id=NEW.invocation_id)
BEGIN SELECT RAISE(ABORT,'DETECTOR_INVOCATION_TERMINAL'); END;

CREATE TRIGGER detector_candidate_before_end BEFORE INSERT ON candidates
WHEN EXISTS(
 SELECT 1 FROM raw_detection_receipts r
 JOIN detector_invocation_ends e ON e.invocation_id=r.invocation_id
 WHERE r.receipt_id=NEW.receipt_id
)
BEGIN SELECT RAISE(ABORT,'DETECTOR_INVOCATION_TERMINAL'); END;

CREATE TRIGGER detector_receipt_within_asof BEFORE INSERT ON raw_detection_receipts
WHEN NOT EXISTS(
       SELECT 1 FROM detector_invocations
       WHERE invocation_id=NEW.invocation_id
         AND instrument_id=NEW.instrument_id
         AND timeframe=NEW.timeframe
         AND detector_id=NEW.source_detector_id
         AND detector_version=NEW.source_detector_version
     )
 OR NEW.available_at_us > (
       SELECT as_of_us FROM detector_invocations WHERE invocation_id=NEW.invocation_id
     )
BEGIN SELECT RAISE(ABORT,'DETECTION_INVOCATION_MISMATCH_OR_ASOF'); END;

CREATE TRIGGER candidate_matches_receipt BEFORE INSERT ON candidates
WHEN NOT EXISTS(
 SELECT 1 FROM raw_detection_receipts r
 WHERE r.receipt_id=NEW.receipt_id
   AND r.occurrence_key=NEW.occurrence_key
   AND r.instrument_id=NEW.instrument_id
   AND r.timeframe=NEW.timeframe
   AND r.pattern_family=NEW.pattern_family
   AND r.direction=NEW.direction
   AND r.trigger_time_us=NEW.trigger_time_us
   AND r.detected_at_us=NEW.detected_at_us
   AND r.available_at_us=NEW.available_at_us
   AND r.evidence_refs_json=NEW.evidence_refs_json
   AND r.source_detector_id=NEW.source_detector_id
   AND r.source_detector_version=NEW.source_detector_version
   AND r.taint=NEW.taint
)
BEGIN SELECT RAISE(ABORT,'CANDIDATE_RECEIPT_MISMATCH'); END;

CREATE TRIGGER detector_end_counts BEFORE INSERT ON detector_invocation_ends
WHEN NEW.receipt_count <> (
       SELECT count(*) FROM raw_detection_receipts WHERE invocation_id=NEW.invocation_id
     )
 OR NEW.candidate_count <> (
       SELECT count(*)
       FROM candidates c
       JOIN raw_detection_receipts r ON r.receipt_id=c.receipt_id
       WHERE r.invocation_id=NEW.invocation_id
     )
 OR (
       NEW.status='COMPLETED'
       AND EXISTS(
         SELECT 1 FROM raw_detection_receipts r
         WHERE r.invocation_id=NEW.invocation_id
           AND NOT EXISTS(SELECT 1 FROM candidates c WHERE c.receipt_id=r.receipt_id)
       )
     )
BEGIN SELECT RAISE(ABORT,'DETECTOR_END_COUNT_MISMATCH'); END;

CREATE TRIGGER immut_detector_invocations_update BEFORE UPDATE ON detector_invocations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_detector_invocations_delete BEFORE DELETE ON detector_invocations BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_detector_invocations_insert BEFORE INSERT ON detector_invocations
WHEN EXISTS(SELECT 1 FROM detector_invocations WHERE invocation_id=NEW.invocation_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_raw_detection_receipts_update BEFORE UPDATE ON raw_detection_receipts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_raw_detection_receipts_delete BEFORE DELETE ON raw_detection_receipts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_raw_detection_receipts_insert BEFORE INSERT ON raw_detection_receipts
WHEN EXISTS(
 SELECT 1 FROM raw_detection_receipts
 WHERE receipt_id=NEW.receipt_id
    OR (invocation_id=NEW.invocation_id AND receipt_index=NEW.receipt_index)
)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_candidates_update BEFORE UPDATE ON candidates BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_candidates_delete BEFORE DELETE ON candidates BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_candidates_insert BEFORE INSERT ON candidates
WHEN EXISTS(SELECT 1 FROM candidates WHERE candidate_id=NEW.candidate_id OR receipt_id=NEW.receipt_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;

CREATE TRIGGER immut_detector_invocation_ends_update BEFORE UPDATE ON detector_invocation_ends BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_detector_invocation_ends_delete BEFORE DELETE ON detector_invocation_ends BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
CREATE TRIGGER immut_detector_invocation_ends_insert BEFORE INSERT ON detector_invocation_ends
WHEN EXISTS(SELECT 1 FROM detector_invocation_ends WHERE invocation_id=NEW.invocation_id)
BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
