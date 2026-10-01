# Atlas v2 P0-5 — Label Tasks, Submission Groups, Views & Agreement

Owner: Ali Shariati  
Status: implementation scope

P0-5 implements the smallest correct label evidence system required before candidate capture/evaluation. It closes the retrospective-vs-operational time boundary: a label created later about an earlier chart may be useful research evidence but can never become an earlier operational decision input.

## Task identity

- LabelTaskSeed identity binds study_id, instrument, timeframe, dataset_id, visible_data_cutoff_us, lookback_bars, blind_mode, repeat_index, and include_forming_bar=false.
- Blind modes: NONE, IDENTITY, IDENTITY_PRICE.
- The task seed exists before any blind transform.
- LabelTask identity binds seed_id + canonical transform parameters.
- IDENTITY_PRICE transform parameters derive only from HMAC(study_secret, seed_id), so the identity graph is acyclic.
- Study secrets are never stored in the evidence database.
- Historical label task creation is a LABEL_TASK read route and must pass the P0-3 holdout guard before the task is returned.

## Submission groups

- A LabelSubmissionGroup is the atomic human/engine statement.
- Identity binds task_id + labeler_id + request_key.
- Request retries with the same key/payload return the original group and original server timestamp.
- Same key with changed payload is rejected.
- Kinds: INTERPRETATIONS or ABSTENTION.
- Modes: OPERATIONAL, RETROSPECTIVE, LEGACY_IMPORT, ENGINE.
- submitted_at_us is server-stamped once.
- OPERATIONAL: operational_available_at_us == submitted_at_us.
- All other modes: operational_available_at_us is NULL.
- RETROSPECTIVE adds RETRO_LABEL taint.
- LEGACY_IMPORT adds INFERRED_RECONSTRUCTION taint by default.
- Revisions are new groups. supersedes_group_id must refer to the current prior group for the same task + labeler. No update/backdating/forks.

## Interpretations / anchors

- INTERPRETATIONS groups carry 1–3 ranked alternatives.
- Rank unique 1–3; optional probability_ppm values sum to <= 1,000,000.
- Trend: BULLISH, BEARISH, RANGE, TRANSITION.
- Confidence: 1–5.
- Optional correction_depth_ppm remains continuous.
- Optional correction_class: MINOR, MAJOR, NONE_YET, UNCLASSIFIED_EQUALITY.
- Anchors: IMPULSE_START, IMPULSE_END, CORRECTION_EXTREME; side HIGH/LOW.
- EXACT_BAR and INFERRED_RECONSTRUCTION anchors must lie on a complete bar: bar close <= visible_data_cutoff_us.
- UNKNOWN_LEGACY anchors have no bar/confirmation time.
- confirmation_time_us, when present, is >= bar close and <= cutoff.
- P0-5 stores integer anchor prices. Exact chart-extreme snapping against derived H4 is enforced when the operational labeling UI/data adapter is built in P1; P0-5 does not guess a broker H4 grid.

## Label views

- OperationalLabelView(as_of=d) can see only OPERATIONAL groups with operational_available_at_us <= d and visible_data_cutoff_us <= d.
- Retrospective, legacy, and non-operational engine groups are never operationally visible.
- ResearchLabelView may include all label modes, preserving each group’s taint.
- Selection first takes the latest eligible group per authorized labeler, abstentions included.
- A versioned LATEST_AUTHORIZED_OWNER policy may then choose the most recently submitted authorized statement. An abstention is never skipped to resurrect an older label.
- LabelSetPin binds view kind + sorted selected group IDs + selector policy version. Later revisions create a new pin; old runs retain their original pin.

## Agreement

P0-5 provides small deterministic metrics for declared label studies:
- direction agreement;
- Cohen’s kappa on non-abstaining direction pairs;
- abstention rate;
- anchor agreement within k bars for k = 0, 1, 3.

No threshold automatically promotes an H4 engine or replaces owner authority.

## Scope exclusions

No label UI, no broker chart assumptions, no automatic H4 replacement, no candidate detection, no strategy gates, no outcome simulation, no execution, no AI provider, no paid service.
