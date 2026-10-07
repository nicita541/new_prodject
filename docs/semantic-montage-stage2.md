# Semantic montage FIX STAGE 2

Stage 2 implements separate understanding and selection confidence, bounded local/dense/global adjudication and an unresolved selection gate. Previous Stage 1 and the user's intervening commits are preserved. The independent React hotfix was completed first as `72034c638ec2ac4733f5715632e6fbf515c9f733`.

## Selection protection

- Missing/failed/uncertain evidence cannot authorize a whole-event keep-all fallback.
- Positive consequential action/reaction evidence cannot silently become DROP; authoritative whole-unit nonstory proof remains an exclusion.
- Source selection checks confidence bounds, exact CURRENT unit ASR quotes, actual frame timestamps inside the supplied view and source-derived frame index domains.
- Provided ASR accepts only source transcript fields and scalar metadata, including validated resume provenance; nested precomputed semantic answers cannot enter production through the transcript interface.
- Adjudication caches include bounded storyboard implementation and runtime policy, so changed visual evidence geometry invalidates derived decisions.
- Global corrections preserve provenance and unresolved analysis remains visible before export.

## Resumed unfinished item after hotfix

Multi-page global review retained original frame labels but wrote the size of the current page group as `frame_count`. In a nine-page storyboard, the second group contains labels 217–324 but previously declared a domain of only 108. The final selection gate therefore rejected a genuinely supplied frame 217.

`app/global_verification.py` now derives the ceiling from the actual source index-to-time keys, never the model's claimed indices. Version 3 invalidates stale derived output. Two new regressions in `tests/test_global_verification.py` prove that frame 217 keeps its original timestamp and passes the gate, while invented frame 999 remains unresolved and does not expand authority.

## Executed checks

- 39 global-verification tests passed, including both new page-domain regressions.
- Full Python suite: **764 passed in 93.455 seconds**. Compared with Stage 1's 650, this includes 112 Stage 2 regression additions and 2 independent React contract tests.
- Legacy UI: 24 passed. React's unchanged hotfix snapshot already passed 78 tests, production build and lint (7 effect warnings); 4 server routing pytest checks passed.
- `git diff --check` passed.

## Actual model evidence and remaining quality work

The source-only production run under `scratch/raw_video_quality/production_runs/20261007-stage2-I/raw-003` made 23 actual model requests. It returned unresolved selection, retained zero seconds and did not render. Its original input manifest, responses, frame hashes, actual-analysis and diagnostics are preserved. This is a detected quality failure, **not a successful E2E test**. It is not used to claim completion of raw-video A–J.

Next: apply Stage 3's measured motion/profile and mandatory-before-optional allocation; then Stage 4's automatic relations/arcs, continuity recovery and final quality gate. Overall completion still requires successful actual source-only raw-video E2E A–J without injected semantic answers.
