# 0040 — Source-bound montage review assistant

Date: 2026-10-13

## Problem
Playback review could reveal an opening left in a part or clipped speech, but there was no route from a natural-language remark to a new corrected version. Whole-episode reanalysis repeats expensive upstream work and loses the reviewed edit's context.

## Decision
`review_feedback` owns bounded interpretation, corrective source actions, clarification, immutable base validation, retry checkpoints and version-linked history. `jobs` accepts feedback only for a completed, registered-source-owned job with valid cached analysis/plan; archived owners must be restored first. Legacy library ownership is resolved before assigning the new job. The normal single owned worker retains inference/cancellation ownership.

`GET /api/jobs/{id}/feedback` reads history without inference. `POST` accepts canonical UUID `operation_id`, nonblank `text` (up to 2000 characters), actual plan `part_index` and optional finite source position. Identical replay returns the same correction job; different content under the same ID is rejected. A journal links the source version to the new job. Immutable base snapshots and actual source SHA-256 bind the request. Four bounded earlier exchanges provide follow-up context. History checks source/episode ownership on every link and handles deleted versions.

The selected provider interprets only `opening` and `speech` actions over supplied part IDs. Low-confidence, unsupported or unclear comments ask for clarification. Position-scoped “here” selects the nearest retained cut at the player’s source position, without arbitrary timestamp authority. Model output cannot choose paths, commands, external endpoints or another episode.

Opening repair forces existing whole-production review for affected source events, retaining independent boundaries and original-anchor checks. The new hypothesis participates in cache/request identity but remains a hypothesis. No original proof means no deletion or claimed success. Normal final quality validation still owns export permission.

Speech repair increases bounded original-audio margins for affected cuts (lead at most .6 s, tail at most 1.5 s), preserving omitted-word and confirmed-exclusion barriers. Incomplete source replies can be restored only within existing positive unit proofs. Both planners, retention costing and the independent gate use the same source-analysis override policy; a plan cannot authorize its own padding. Overrides persist for later incremental/plan-only runs. No speech is synthesized and missing source audio is not invented.

Corrections use frozen upstream analysis, ordinary replanning and the existing quality recovery/export gate. A validated correction-analysis checkpoint and immutable bases prevent retry from applying an edit twice. Unchanged cuts require clarification, never a completed-repair claim. Per-part MP4/SRT fingerprints now cover actual cuts/focus, captions, source/probe, appearance, renderer code, chosen music and ducking. Unchanged parts survive changes elsewhere; old global checkpoints conservatively miss once.

Studio keeps playback and the timeline in a viewport-sized workspace, with Shorts/source/comparison controls; part navigation preserves the selected viewing mode. Draft status remains identifiable in the attempt selector without a large playback banner. Part selection/export uses a modal side drawer; message history/status and the corrected-version link use a separate native dialog. Opening/closing these tools preserves player nodes, playback positions and unsent feedback; selecting a part closes the drawer. Submission/polling replaces only assistant messages, preserving the player. It records the active player, maps output time through original cuts, escapes user/model text and retains operation IDs after lost responses. Polling ends outside review or when no correction is active. The previous version remains selectable. Plan-only results show source playback because no rendered Shorts exist.

## Compatibility and rollback
Previous plans/exports remain unchanged; source jobs gain only feedback journals. Request/base/result/analysis files are additive. Disable routes/UI while no correction worker is active to stop new submissions without removing versions. Existing processing modes, finishing and manual-provider waiting/cancellation remain. Include feedback files in ordinary job backups.

Corrections operate on the base source plan and its ASR-derived captions. Job-owned manual finishing caption overrides are not automatically remapped through changed cuts; finishing remains available for the new version and should be reviewed there.

## Verification and limits
Fake-worker/provider/media tests cover idempotency, immutability, ownership, archive/origin/input guards, follow-up context, scoped cuts, confirmed/unconfirmed OP, speech barriers, source-policy enforcement, unchanged-edit clarification, retry reuse and part cache identity. Studio DOM smoke covers escaped text, part/position/operation context, preserved playback and version navigation. These checks do not establish real model interpretation or encoded-video/audio quality. Initial supported categories are opening and clipped speech; other requests require clarification.
