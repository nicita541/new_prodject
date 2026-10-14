# Goal

Keep reusable clean montage parts so subtitles, music and cards are applied without cutting the full episode again. Show start, ongoing work and completion in the correct order.

# Current state

Initial and finishing rendering both open the episode once per cut. Finishing forces libx264 and reports progress only between parts. Applying a one-part caption edit requests all parts.

# Constraints

Preserve source media, plans, captions, ownership, cancellation, bounded workers and base outputs. All media/cache files stay in the workspace. Clean parts must contain the complete source frame and original selected audio, with no added captions/music/card. Preserve output-clock timing and focus at cut boundaries. Legacy projects remain readable.

# Implementation

1. Add validated, atomically published lossless clean parts at original resolution under each job, keyed by source identity, audio selection and exact cuts. Remap focus to their output clock. New initial renders retain these parts; existing jobs build them lazily. Short previews reuse a present master without forcing a full build.
2. Apply finishing from clean parts with the existing tested GPU selection/fallback. Reuse only unchanged latest presentations (matching plan, effective captions and settings); keep explicit re-export available. Report continuous FFmpeg time and preparation/queue phases.
3. Add a persistent UI status and replace old success notices immediately on submission. Completion follows successful export and refreshed files.
4. Verify real multi-cut audio/video timing, cache reuse/invalidation, focus boundaries, failure/cancellation and pending/failing DOM flows. Benchmark an isolated real part without replacing user exports, then activate the checked backend when idle.

# Validation

Repository pytest tests for media, finishing and production entry points; native Studio build/lint/DOM checks. Real FFmpeg clean/final output probes and repeated cached render timings, with all evidence under temp.

# Risks and rollback

Lossless original-resolution masters consume additional disk space. They are disposable derived files, published only after validation; removing a job's clean tree recreates them later. Old styled outputs cannot serve as masters because captions/music cannot reliably be removed. Cache versions separate changed algorithms. Revert new call sites/module to restore direct source rendering; original plans/output files are untouched.

# Progress

- [x] Clean-part storage and integration
- [x] Finishing reuse, hardware selection and progress
- [x] UI notification sequencing
- [x] Tests, real media verification and documentation
- [x] Idle activation

Verification: full repository run 1461 passed / 654 subtests (240.04 seconds).
The final focus-exit boundary adjustment subsequently passed all five clean-part
tests. Native Studio build, lint and both DOM checks passed, including held
running/completed-refresh/failed export requests. Four older pipeline fixtures
were updated to stub the new media preparation boundary as well as final render.

Real source part: clean master creation 8.19 seconds, cached-master NVENC
presentation 29.58 seconds versus 46.66 seconds in the preceding CPU export.
All six current montage masters have been prepared. Six real final MP4s passed
1080x1920 / 30 fps / H.264 / AAC / exact-plan-duration validation and HTTP range
checks. Reapplying all six unchanged parts completed in 1.60 seconds, created no
render work folders and reused all six verified outputs. Original MP4 and plan
SHA256 hashes remained identical. Evidence: `temp/clean-shorts-verification/`.
Final idle Studio PID 51808 has a verified current backend/UI identity and serves
the six latest completed cached files. Browser visual automation remained
unavailable; native DOM execution and an actual rendered frame were inspected.
