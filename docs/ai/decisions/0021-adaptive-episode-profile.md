# Adaptive episode profile and retention budget

## Decision

Shot suppression remains a montage-camera policy. Every raw FFmpeg candidate retains its score, local density, adaptive threshold, acceptance and suppression reason. Accepted shots keep their original IDs. Semantic grouping may inspect suppressed boundaries and their original source-frame descriptors; camera noise cannot silently erase a real location transition.

`episode_profile` derives initial factual speech/pause/visual-change metrics and later refines them with semantic scenes and confirmed narrative actions. Profiles are dialogue_slow, balanced, action_dense or mixed. Scene grouping receives profile settings, and their values enter cache identity. Scene-score density is explicitly a visual-change proxy, not measured optical flow or recognized action.

Dramatic selection uses a material-specific min/optimal/max retention range. Candidate cost is the duration of actual source-unit selections or compressed replies rather than the full scene envelope. Validated unit decisions, including unresolved-recovery fallback and actions during speech, survive planning. Profile and budget are persisted in job and pipeline diagnostics.

## Compatibility and rollback

Shot and semantic detector versions invalidate their own decisions; analysis version 11 and planner version 13 invalidate downstream plans. List-of-shots and source interval APIs remain compatible through additive metadata. Original sources and ASR remain reusable. Revert the stage to restore previous profile and selection policy.

## Validation and limits

Tests cover suppression provenance, dense-action location changes, source-frame extraction, equal-duration materials with different profiles, source-bounded budgets and long quota-pressure selection. Profiles are deterministic heuristics; real model judgments and real episode montage quality require separate visual review.
