"""Frozen P0 Definition-of-Done manifest and logical identity graph."""
from __future__ import annotations

from datetime import datetime, timezone


def _us(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1_000_000)


FX_EURUSD_6W = {
    "name": "fx_eurusd_6w",
    "instrument_id": "EURUSD",
    "start_us": _us("2026-03-01T00:00:00"),
    "end_us": _us("2026-04-12T00:00:00"),
    "timeframes": ["M1", "M15"],
    "dst_markers_us": [
        _us("2026-03-08T10:00:00"),  # US DST transition window
        _us("2026-03-29T01:00:00"),  # EU DST transition window
    ],
    "scenarios": [
        "PLANTED_SETUPS",
        "GAPS",
        "DELAYED_CONSTITUENTS",
        "OVERLAPPING_EXPORTS",
        "CALENDAR_SOURCE_STAMPED",
        "CALENDAR_OBSERVED_BY_ATLAS",
        "CALENDAR_UNKNOWN",
        "REVISIONS",
        "DISTINCT_SAME_BAR_OCCURRENCES",
    ],
}

P0_DOD_TESTS = {
    "replay_fresh_reused": [
        "tests.atlas2.test_evaluation_replay.EvaluationReplayTests.test_retry_writes_zero_new_evidence_rows",
        "tests.atlas2.test_evaluation_replay.EvaluationReplayTests.test_fresh_store_different_attempt_has_same_replay_digest",
    ],
    "semantic_prefix": [
        "tests.atlas2.test_evaluation_replay.EvaluationReplayTests.test_cross_dataset_semantic_prefix_and_control",
    ],
    "crash_resume": [
        "tests.atlas2.test_evaluation_replay.EvaluationReplayTests.test_crash_resume_digest_equals_uninterrupted_run",
    ],
    "gate_exception_preserves_capture": [
        "tests.atlas2.test_evaluation_replay.EvaluationReplayTests.test_gate_fault_rolls_back_evaluation_not_capture_and_resume_works",
    ],
    "same_bar_occurrences": [
        "tests.atlas2.test_candidate_capture.CandidateCaptureTests.test_occurrence_key_changes_with_causal_anchor_time",
    ],
    "overlapping_exports_revision": [
        "tests.atlas2.test_data_spine.DataSpineTests.test_overlapping_observations_one_fact_and_revision_precedence",
    ],
    "htf_delayed_missing": [
        "tests.atlas2.test_data_spine.DataSpineTests.test_h4_derives_from_visible_m15_and_ignores_source_h4",
        "tests.atlas2.test_data_spine.DataSpineTests.test_missing_constituent_remains_incomplete_after_close",
    ],
    "calendar_pit_nonpit": [
        "tests.atlas2.test_data_spine.DataSpineTests.test_unknown_calendar_is_non_pit_only_and_tainted",
    ],
    "labels_causality": [
        "tests.atlas2.test_labels.LabelTests.test_retrospective_never_enters_operational_view",
        "tests.atlas2.test_labels.LabelTests.test_revision_abstention_is_not_skipped_by_operational_selector",
    ],
    "request_key_retries": [
        "tests.atlas2.test_store_foundation.StoreFoundationTests.test_request_retry_keeps_result_and_time",
        "tests.atlas2.test_labels.LabelTests.test_operational_submission_retry_and_changed_payload_conflict",
        "tests.atlas2.test_research_registry.ResearchRegistryTests.test_prereg_hash_stability_and_request_retry",
    ],
    "holdout_persistence": [
        "tests.atlas2.test_research_registry.ResearchRegistryTests.test_dataset_versions_do_not_affect_holdout_identity",
        "tests.atlas2.test_research_registry.ResearchRegistryTests.test_adaptive_second_session_marks_inspected",
    ],
    "sealed_aggregates_terminal": [
        "tests.atlas2.test_store_foundation.StoreFoundationTests.test_seals_reject_children_in_sql_and_repository",
        "tests.atlas2.test_candidate_capture.CandidateCaptureTests.test_terminal_invocation_rejects_new_receipts_and_candidates",
    ],
    "backup_restore_recovery": [
        "tests.atlas2.test_hardening.HardeningTests.test_format2_backup_checkpoint_restore_records_recovery_epoch",
    ],
    "artifact_boundary": [
        "tests.atlas2.test_architecture.ArchitectureBoundaryTests.test_p0_has_no_legacy_broker_or_network_imports",
        "tests.atlas2.test_architecture.ArchitectureBoundaryTests.test_importing_all_atlas2_modules_does_not_load_legacy_or_mt5",
    ],
    "legacy_hashes": [
        "tests.atlas2.test_legacy_import.LegacyImportTests.test_read_only_source_hash_and_schema_checkpoint",
    ],
    "hardware_baseline": [
        "tests.atlas2.test_hardening.HardeningTests.test_hardware_baseline_recorded_without_threshold",
    ],
}

# Directed edge: identity type -> identity types it logically depends on.
IDENTITY_DEPENDENCIES = {
    "raw_blob": set(),
    "component": set(),
    "recovery_epoch": set(),
    "observation": {"raw_blob", "component"},
    "fact": {"component"},
    "dataset": {"fact", "observation", "component"},
    "label_task_seed": {"dataset"},
    "label_task": {"label_task_seed"},
    "label_group": {"label_task"},
    "interpretation": {"label_group"},
    "anchor": {"interpretation"},
    "label_pin": {"label_group"},
    "strategy": set(),
    "run_manifest": {"dataset", "label_pin", "strategy", "component"},
    "run_attempt": {"run_manifest", "recovery_epoch"},
    "detector_invocation": {"run_attempt", "dataset"},
    "occurrence": {"fact"},
    "receipt": {"detector_invocation", "occurrence", "fact"},
    "candidate": {"receipt", "occurrence"},
    "snapshot": {"dataset", "fact"},
    "capture_unit": {"snapshot", "candidate"},
    "evaluation_context": {"capture_unit", "label_pin"},
    "relation": {"evaluation_context", "candidate"},
    "gate": {"evaluation_context", "candidate", "relation", "fact", "label_group"},
    "arm": {"candidate", "strategy", "evaluation_context", "gate"},
    "outcome_batch": {"dataset"},
    "outcome": {"outcome_batch", "arm", "candidate", "dataset"},
    "audit": {"recovery_epoch"},
}


def assert_identity_graph_acyclic() -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"identity dependency cycle at {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in IDENTITY_DEPENDENCIES[node]:
            if dependency not in IDENTITY_DEPENDENCIES:
                raise ValueError(f"unknown identity dependency {dependency}")
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for name in IDENTITY_DEPENDENCIES:
        visit(name)
