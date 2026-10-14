# Analysis preparation performance

## Goal
Reduce source-image preparation gaps and excessive local4B request fanout for project «д», episode 1, preserving source frame coverage, speech boundaries and uncertainty validation.

## Current state
The cancelled job `cef8da9c-4a98-4284-b2e8-4ccd0870562d` contains 556 boundary requests and 414 scene requests. Its full 1420-second source plans 508 scene chunks with an 18-frame single-page limit. Every storyboard hashes the full source and launches FFmpeg separately per frame; legacy overview pages repeat this overhead. Boundary selection uses independent time buckets that can select almost coincident candidates across bucket edges.

## Constraints
All artifacts remain inside this workspace. Preserve the dirty working checkout. Develop in `temp/analysis-performance-worktree` on `codex/analysis-preparation-performance`, using a snapshot of current source changes. Do not restart the user job or use remote inference. Preserve exact decoded source PTS, cancellation, image/cache integrity, 18-frame readable pages and conservative unresolved evidence.

## Implementation
1. Measure saved request fanout and actual source preparation before changes.
2. Batch exact-PTS decoding, reuse source hashes while the file stamp is unchanged, and use the same extraction path for legacy overview images.
3. Permit at most two readable CURRENT pages for paged providers, with existing one-page behavior for other providers. Enforce real temporal spacing between boundary verifications and keep all deferred source evidence.
4. Add regression protection, measure preparation and planned request counts, and apply only the task-specific changes after checking that baseline files did not change.

## Validation
Use workspace portable Python and FFmpeg. Run bounded storyboard, frame contract, boundary triage, semantic pipeline, recovery and semantic identity checks with pytest. Compare actual source-frame extraction timings and PTS before/after, and replay chunk planning on the saved transcript/scenes without model inference. A short local4B comparison may verify the expanded CURRENT pages; report limits separately from a full episode rerun.

## Risks and rollback
More CURRENT pages may exhaust model context or output limits; keep two-page maximum and check real local requests. Decoding must retain source PTS on nonzero-start and variable-rate video, repair tampered caches and never publish a page after source mutation/cancellation. Source changes invalidate the in-process hash cache via size, mtime and ctime. Revert only these task-specific edits; preserved baseline files live under the worktree's `scratch/performance-baseline`.

## Progress
- [x] Characterized saved execution and source fanout.
- [x] Created isolated worktree and preserved current source baseline.
- [x] Implemented batch preparation, two readable local CURRENT pages, and spacing for repeated boundary candidates while protecting explicit state/dialogue probes.
- [x] Measured original source preparation (~4.2x faster) and real local4B on 72.76 seconds (26 versus 11 requests; expanded input at most 3999 tokens). First old request was cold, so total episode speed is not inferred from the short wall-clock comparison.
- [x] Applied only task edits after checking unchanged source baselines. Final working-checkout validation: 170 tests and 77 subtests passed. Detailed measurements and limitations: `scratch/analysis-performance/report.md`. The product job remains cancelled; no complete episode rerun/export was started.
