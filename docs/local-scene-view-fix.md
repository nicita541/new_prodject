# Local analysis: short silence at a visual-view boundary

The local UI run `3eaa3d60-ffe6-4182-809e-0f3e2c4dfae5` stopped in scene analysis with `Indivisible source unit exceeds the bounded visual view`. Its first attempt finished on 2026-10-09 at 09:37:13 UTC, with no exported parts.

The failure was reproduced directly from its ordinary saved `scenes.json`, `transcript.json` and `shots.json`. Scene `scene_0074` spans 178.25–189.022322 seconds. A technical child covering 178.25–182.09 contains an 80 ms silent unit followed by a spoken phrase. The initial view requests 12 samples, while recovery requests 13. The splitter excluded source-unit edges within 80 ms of a child endpoint, incorrectly rejecting the safe speech onset at 178.33.

`bounded_chunks` now accepts existing word-safe unit edges whenever they leave positive child intervals. It retains the 12-frame limit for initial and recovery views, semantic scene ownership, full interval coverage and word integrity. It does not create story boundaries, infer source facts or trim samples to make a request fit. A genuinely indivisible oversized word still raises rather than cutting speech.

Validation performed:

- 80 focused semantic pipeline, understanding, scene detection and semantic identity tests passed, including the short-pause regression at zero and nonzero source offsets and an oversized-word guard.
- All 478 saved source scenes were checked: 950 technical children, contiguous coverage and at most 12 requested frames for both inference modes, with no splitting failures.
- Actual FFmpeg extraction from the original video succeeded for both repaired children and both sampling modes. Every returned frame timestamp lies within its child interval.
- 29 nearby bounded-storyboard and job lifecycle tests passed, including retry/checkpoint preservation.

A normal retry can reuse the unchanged ASR, perception and scene-detection checkpoints. Analysis identities change with this code fix, so earlier scene analysis is recomputed rather than relabelled as validated by the new code. These checks establish the fix for this failure; they do not establish successful full export or editorial quality.
