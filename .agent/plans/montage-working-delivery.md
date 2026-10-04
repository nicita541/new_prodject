# Usable montage delivery and review diagnostics

## Goal
Finish the working branch so the user can launch montage, understand processing, and review a corrected E01 without clipped speech, ending credits or positively identified empty walking. The requested debug checkbox explains why actual retained timeline spans survived. Further unrelated improvements belong on a separate branch.

## Current state
Workspace is F:/new_prodject, branch codex/montage-quality. Source checkpoints: 8dcd0e0 removes monetary gates; ef90d37 adds seven processing checkpoints/two mode choices; 629b208 adds pure ED authority and dense review of low-confidence production candidates. Node UI suite passed 13 tests; Python suite passed 347 tests before later speech/pacing/debug changes.

The actual normal episode 926f51e4-4c81-47a9-b85c-d556493edf45, project «перекус», exported job 98291dad-343d-434c-aa2a-9fbd439af3fd (15 parts). User rejected its continuity and ending. A human-reviewed corrected copy daba310b-e2df-4702-8600-bbb9a0acf12a has 14 parts, preserves old outputs, restores 71.120333–74.241 seconds and removes the tail from 1335.042 seconds. Four changed parts decoded successfully; all 14 probed and SRT bounds checked. It is still rejected: part 1 ends mid-word and parts 2/3 contain empty walking. Do not call this delivery accepted.

Local isolated Whisper corroborated «Понимаю.» at 83.680–84.680, versus cached 83.700–84.620. Source exterior continues before the true OP transition at 88.005; exclusion from 84.62 clips speech. Retaining through 85.23 provides the usual 0.55-second handle without restoring OP. ED starts at exact shot boundary 1335.042; 1425 is production-committee credit, 1427–1430 announces the second episode, and tail is black. There is no evidenced current-episode post-ED plot in this source.

The earlier 34-warning list included removed ED units. The existing plan route now derives a filtered summary from final cuts and exact unit ranges; on the older rejected Daba copy it returns 19 warnings, no profile notes, and no warnings for removed events 0034/0035. Its debug DTO reports 205 explicit retained reasons (200 model-atmosphere annotations and 5 uncertainty intervals); atmosphere is labeled as a model rationale, not verified story fact. Browser UI keeps this view off by default. These counts describe the old rejected copy, not the pending correction.

## Constraints
- Keep tools, temporary files, media, caches and dependencies inside the workspace. Never commit source media, secrets, raw provider payloads or private job state.
- Monetary accounting remains retired. Requests have one send plus two retries; preserve cancellation, auth/TLS checks and strict IDs.
- Preserve jokes/reactions and important silent causal action; motion/silence alone cannot classify a scene. Ordinary prolonged walking/pans are not automatically atmosphere or plot.
- Prefer current cached evidence and targeted rechecks; avoid whole-episode ASR or repeated initial analysis for reviewed corrections.
- Old exports stay intact. New reviewed copies carry explicit provenance; a manual correction is not evidence of a fresh full remote analysis.
- Model-supplied debug text is data, rendered safely, never HTML or instructions. Public diagnostics expose bounded timings/reasons, not paths, prompts, keys or private responses.

## Implementation
1. Correct production-unit speech handles/OP boundary handling and regressions. Backend owner: montage_recovery (production_sequence/source_roles/planner as needed).
2. Identify and correct retained empty walking from actual parts 2/3, with positive visual evidence and speech/action safeguards. Owner: processing_checkpoints (pacing/story/editorial and their tests).
3. Recompute relevant diagnostics for actual retained intervals; distinguish informational retention from actionable uncertainty. Add off-by-default timeline checkbox and reason markers/details. Owner: processing_checkpoints_review (quality module, static UI/tests, narrowly scoped read-only server interface if needed).
4. Combine validated cut corrections into a new source-bound export, re-render only changed parts, preserve earlier versions. Publish only a valid completed copy linked to the same episode.
5. Integrate, run meaningful Python/UI checks and media QA; restart only the owned idle server if endpoint changes require it. Open the exact final review route in the built-in browser and retain it.
6. Commit the working delivery and concise QA/context; leave unrelated improvements for another branch.

## Validation
Full discovered Python tests and mocked Node UI tests after source changes. Specific regressions: speech tail/next-reply clamp, pure ED vs interleaved/post-ED plot, empty neutral walking vs important quiet action/reactions, stale removed-unit diagnostics, debug off/default/toggle/safe text, current-stage aliases and legacy provider settings. Probe final output count, durations and audio/video format; verify SRT bounds and full-decode changed parts. Inspect actual first-part speech/OP boundary, final pre-ED boundary and targeted walking cuts with source evidence. Browser must show the exact new job, not a previous fallback. Unit/media tests do not certify the whole episode's artistic quality.

## Risks and rollback
Conservative labels can over-preserve neutral motion; aggressive trimming can remove silent story. Require positive evidence and preserve uncertain causal/reaction beats. Rounded ASR ends are not exact speech boundaries; add bounded handles without crossing verified production transitions. Diagnostic data may be missing in historical jobs: show unavailable rather than fabricate explanations. Roll back source via Git; original jobs and media remain available for comparison.

## Progress
- [x] Launch and seven processing checkpoints verified; old modes removed from new-job UI.
- [x] Pure ED generic fix, independent review and 347-test baseline passed.
- [x] First reviewed 14-part correction exported and technically checked; user feedback recorded as rejection.
- [x] Speech-tail/OP handle code and regression cover a 85.23-second endpoint before the 88.005-second OP; final media verification remains pending.
- [ ] Empty walking/holds positively reviewed and fixed: 11 proposed source cut ranges (36.193 seconds total) are pending combined export. The basket label cut is corrected to start at 283.5 seconds; the 289-second retrieval remains.
- [x] Actual-plan diagnostics and debug timeline implemented; mocked Node suite reports 16 passing tests and the full Python suite 361 passing. Quality helper/API tests passed 8 focused cases. Browser verified the old Daba plan loads 17 distinct warnings and 205 debug markers; adjacent marker precision polish remains in progress.
- [ ] Combined final export and browser review verified.
- [ ] Final delivery Git/context checkpoint and future-branch separation recorded.
