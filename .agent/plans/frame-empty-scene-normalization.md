# Goal

Keep the local source-only analysis running when word-safe scene boundaries create an interval containing no decoded video PTS. Preserve every source interval and speech boundary, and do not substitute out-of-window frames.

# Current state

Run `3eaa3d60-ffe6-4182-809e-0f3e2c4dfae5` failed during scene 445 while constructing NEXT context for scene 446, at 1375.21–1375.248322. The real source has PTS 1375.2073222222 and 1375.2483222222 around this gap. Its source interval has no video PTS and no ASR words. The same issue would affect CURRENT analysis of scene 446. Merely catching the context error is insufficient.

# Constraints

- Retain the bounded storyboard's strict source-window checks and 12-frame ceiling.
- Coalesce only intervals proven empty by the actual original video PTS, irrespective of duration. Preserve audio and total coverage; do not infer story facts.
- Retain raw scene detector results and record original scene IDs/intervals in analysis provenance.
- Keep normal semantic cache invalidation. No relabelling old inference as new-code validation.
- Preserve previous failed attempts. User requested no continuing supervision; restart through the visible app, then leave the worker independent without another observer.

# Implementation

1. Reproduce the failure and inspect CURRENT/PREVIOUS/NEXT probe outputs.
2. Probe the source frame timeline once before scene analysis. Coalesce frame-empty scenes with adjacent source intervals, retaining original interval provenance and word-safe outer boundaries.
3. Cover initial, middle, final and truly frame-empty inputs, source coverage, real PTS extraction and cache identity invalidation.
4. Verify all remaining scene/chunk/context intervals on the real episode, preserve attempt diagnostics, and use the application's ordinary local retry.

# Validation

Run focused semantic pipeline, bounded storyboard, scene detection/understanding and identity tests. Scan the saved real episode with independently decoded video PTS. Extract the failing source window and repaired neighboring windows through actual FFmpeg. Do not claim a completed export or editorial acceptance from these checks.

# Risks and rollback

Coalescing changes scene analysis input and invalidates its semantic caches, so analysis is recomputed. A frame-empty interval's audio remains included in an adjacent scene. Raw detector scenes stay untouched. Revert the isolated fix to restore prior behavior; preserved attempts remain available.

# Progress

- [x] Reproduced the actual NEXT-context failure and identified the next CURRENT failure.
- [x] Implemented source-PTS-based coalescing and provenance.
- [x] 95 focused regressions passed. Actual 34,050-frame source scan found zero empty views after one interval coalesced; coverage is contiguous.
- [x] Full Python suite passed: 1076 tests in 130.109 seconds. Actual repaired CURRENT, recovery and context extraction passed.
- [x] Saved fix in `177db4b`; restarted the same local job with the visible application's `Повторить` button. The panel resumed automatically and the native worker reported running with no error. Previous attempt metadata/pages/diagnostics are preserved in `scratch/local-run-second-attempt-da7770a1.zip`; immutable original frame caches remain in the job directory. No observer was restarted, respecting the user's request. Successful export remains pending.
