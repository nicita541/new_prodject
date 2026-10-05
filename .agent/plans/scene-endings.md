# Goal
Condense repeated silent views as whole source shots and end variable-length parts at completed beats or deliberate cliffhangers. A 70- or 110-second part is valid; equal lengths must not force a cut in an exchange.

# Current state
On codex/montage-next, planner v9 enforces 90 seconds and chooses the nearest reply boundary to an arithmetic target. Pacing v16 subdivides silent shots every two seconds, producing repeated atmosphere decisions and holes in one view. Latest review job 7153131e retains a long commute in part 2. Its source analysis and manual corrections must remain preserved.

# Constraints
All files/runtimes/cache stay in F:\new_prodject. No source-specific rules or time exclusions in production. Keep source order, complete words/replies, speech handles, verified action/reaction and OP/ED exclusions. Existing jobs remain readable. Never claim semantic quality from fixture tests alone.

# Implementation
1. Review silent shot spans once, without arbitrary two-second internal divisions; keep visual and speech evidence.
2. Add a separately versioned, cached narrative-ending review using actual retained dialogue, visual summaries and existing safe boundary IDs. Persist optional evidence on events; invalid/uncertain review uses an explicit fallback.
3. Replace equal-duration packing with output-time path selection: prefer evidenced closure/cliffhanger, allow 70–110 seconds, use 90 seconds only as a soft target and 120 seconds as the processing ceiling. Preserve source coverage and safe fallback.
4. Verify focused regressions/full tests, run a separate source review/export, synchronize affected docs and record actual limits.

# Validation
No mid-shot two-second holes; speech/verified reactions remain protected. Semantic endings at 70/110 beat closer arbitrary stops; removed gaps map correctly; no duplicated/lost selected material. Reject invented, duplicate, unsafe or low-confidence endings. Cached review must avoid repeated provider calls. Decode actual sample export and inspect source/end frames and audio.

# Risks and rollback
Model descriptions and ASR can miss visual payoffs; retain conservative fallback warnings and show evidence. Long single shots remain if their action is uncertain. Ending review invalidates only final derived decisions, not paid story/source facts. Revert pacing/planner/ending version changes to restore prior algorithm; preserve all previous outputs.

# Progress
- [x] Confirm branch and characterize actual failure.
- [x] Implement whole-shot pacing plus independent long-sequence review, including current neutral-view overrides of tentative atmosphere labels.
- [x] Implement bounded narrative-ending proposals and independent exact last/next dialogue checks. Whole-episode ID lists and six-window lists both misbound future dialogue; twelve nearby output-time candidates fix the observed first/second endings.
- [x] Implement planner v11: flexible length path, 120-second processing ceiling shared with media/audit, complete selected speech handles before source gaps.
- [x] Run 382 Python tests/95 subtests and 20 UI checks. Diff whitespace check passed. One existing Starlette/httpx deprecation warning.
- [x] Export separate temp/scene-endings-final previews 1 and 2, 85.23 and 102.3185 seconds; full decode and contact sheets inspected. Six source/output audio comparisons have correlation >=0.99864 and lag 0 to -0.5ms, including both endings. Part 2 ends at source 375.62 after the complete checkout farewell. The final replay used cache_only and sent no new provider queries.
- [x] Update README, architecture and ADR-0017. Original completed job remains preserved.

## Verification scope
The requested early office/commute/shopping region shrank from 89.124 to 39.703 seconds. Commute event retained footage shrank from 23.489 to 6.592 seconds. The complete source plan was recomputed, but only previews 1/2 were exported and visually/audio checked. Other boundaries can still use explicit fallback; one late ending neighborhood was uncertain. This is not whole-episode or three-source editorial acceptance.

## Full rebuild requested
The user clarified that part 2 was an example and the general change requires rebuilding every part of the current episode. Run a new normal production attempt: source-identical factual/story checkpoints may be reused only through their existing signature checks; final events, plan and exports must be regenerated. Preserve the previous result, audit every new part and review every ending.

- [x] Run the general pacing/sequence/ending pipeline across all 36 source events. Final production attempt: e5aeb8c9-076e-425b-b54f-e847e065e0e6.
- [x] Export all 11 parts (70.967–117.378 seconds), fully decode them, audit chronology and subtitle bounds, and inspect chronological frames in every part plus all source ending sheets. No partial recognized words. Audio excerpts compared against the source; fresh excerpt comparisons resolve the WAV resampling-phase discrepancy, with part 9's offset-dependent comparison recorded separately.
- [x] Record actual full-episode results and select the completed attempt in the studio. Latest dropdown label is 5 October 13:28, with all 11 parts and 22 downloadable MP4/SRT files. Previous exports preserved. One nonfinal boundary (part 1, source 85.17) remains explicitly unconfirmed by the model; sampled source frames and its completed final reply were manually inspected.

First full attempt e864ca7a completed all 36 scenes and exported 11 parts. Its 12 nearest-to-grid ending candidates missed completed beats farther away, producing five unverified boundaries, including a question before the exchange continued. Ending v6 reviews the whole 90-second neighborhood in chronological pages of at most 12 candidates, retaining independent verification. A focused regression checks that farther completed-beat candidates are not lost. Run a successor with validated factual/story/pacing caches, regenerate final events/plan and export all parts again.

Whole-neighborhood proposals still missed some responses. Recovery v3 classifies all actual fallback alternatives, then separately verifies their concrete reasons at >=0.9. A captured real response correctly identified completed invitation/rebuke exchanges but assigned classification confidence 0.55–0.6; treating classification as final authority rejected every useful proposal. The separate strict verification keeps final confidence unchanged rather than lowering it. Focused tests cover recovery from absent proposals and exact cache reuse.
