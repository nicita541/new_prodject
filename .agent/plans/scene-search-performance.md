# Scene search performance

## Goal
Reduce semantic scene-boundary search time while preserving visible evidence, per-boundary validation, uncertainty recovery and previous accepted checkpoints.

## Current state
The latest cancelled episode-1 job has a 17.187-second shot detector, 54-second perception pass, and 2269.359-second semantic scene detection pass. Model verification is the main bottleneck. Existing candidate spacing leaves 470 primary boundary checks on recorded measurements. Each independent check repeats the same instructions and JSON fields. Reliable scalar decisions are cached per original source frame/prompt/model signature.

## Constraints
Work in the existing `temp/analysis-performance-worktree` with current source snapshots. Preserve source data and the user job. Do not use remote inference or install dependencies. Keep exact per-boundary BEFORE/BOUNDARY/AFTER images and strict semantic flags. Test batching before enabling it; fewer HTTP requests alone is not proof of a faster or adequate result.

## Implementation
1. Prototype bounded local batches and compare actual model timings with individual verification on the same source boundaries.
2. If measured improvement supports it, integrate batching in the boundary owner and scene coordinator, preserving existing scalar cache reuse and targeted recovery. Invalid/missing/duplicated IDs and control failures must not become accepted decisions.
3. Add focused tests, measure a source sample, and apply only baseline-checked task edits. If batching is slower or unreliable, retain the scalar path and implement only verified preparation/cache improvements.

## Validation
Use the portable Python/FFmpeg/4B model. Compare per-boundary scope/flags and actual durations, input/output tokens and requests; separate cold-start effects. Run semantic boundary, boundary triage, scene detection/perception, semantic identity and relevant pipeline regression checks.

## Risks and rollback
Batch inputs can exceed model context or mix unrelated scenes; cap batch size, label inputs/outputs explicitly, preserve source ownership and scalar fallback. Model self-confidence is not independent quality evidence. Keep the existing scalar provider contract and saved accepted checkpoints. Revert only this task's patch if measurements do not justify batching.

## Progress
- [x] Characterized actual stage timings and preserved a separate baseline.
- [x] Prototype: six independent initial checks took 33.752 s scalar versus 18.469 s batched. An observed label difference was explicitly retained as a quality limitation.
- [x] Production integration, including targeted recovery: 40.062 s / 7 queries versus 24.715 s / 3 queries on six identical source boundaries after warm-up. Location/physical-change/uncertainty flags matched on this sample. Five real old accepted checkpoints were reused in 0.660 s with zero inference.
- [x] Applied three source files and regression suite after baseline checks. Final working-checkout verification: 178 tests and 81 subtests passed in 52.69 s; diff whitespace check passed. Details: `scratch/scene-search-performance/report.md`. No full-episode rerun, remote request or product-job mutation occurred.
