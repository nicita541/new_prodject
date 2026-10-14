# Analysis runtime performance

## Goal
Reuse local model loads, overlap one upcoming CURRENT storyboard with inference, and hash each unchanged source once per worker without changing prompts, selection, recovery, or stage order.

## Current state
Analysis opens five independent sessions. LocalVision already supports request-level thinking overrides. Storyboard source hashing has a private worker cache; analysis, processing and global verification bypass it. Scene chunks prepare images synchronously before querying.

## Constraints
Preserve the user's dirty checkout and existing provider routing/checkpoint contracts. All files and tests stay under F:/new_prodject. Git metadata is read-only in the sandbox, so development uses an isolated source copy in temp/analysis-runtime-worktree, with baseline hashes checked before integration. No product jobs or remote inference are started.

## Implementation
1. Centralize bounded, stamp-checked in-process source hashing with cancellation and thread synchronization.
2. Give analysis one session owner; retain only the current local model and close it before another model/provider. Set thinking defaults only at sequential stage boundaries.
3. Prepare one following uncached CURRENT chunk on a single worker. Keep model calls, context/recovery, progress and checkpoint publication on the coordinator; stop and drain preparation on exit.
4. Add focused regressions, verify nearby integration behavior and document the ownership decision.

## Validation
Run portable Python pytest against source identity, lifecycle, thinking, scene checkpoints/recovery, real FFmpeg frame contracts, processing modes and semantic identities. Demonstrate overlap using synchronization events, not timing guesses. Model mocks establish orchestration only; any wall-clock/model-load claim requires separate real inference measurements.

## Risks and rollback
Concurrent preparation must use disjoint CURRENT windows and never modify accepted decisions. Cancellation must stop owned decoding and propagate its exceptions. Hash reuse is process-local, never based solely on persisted stamps. Roll back only this task's edits using scratch/runtime-baseline after checking the current checkout has not changed.

## Progress
- [x] Inspected owners, routing, caches and existing validation.
- [x] Preserved baseline in isolated source copy.
- [x] Implemented three optimizations.
- [x] Ran focused and integration checks.
- [x] Integrated task edits and synchronized documentation.

Final validation: working-checkout pytest passed 298 tests and 109 subtests in 63.99 seconds; actual local-model smoke completed five requests with exactly two GPU startups (4B 8.578s; 9B 10.547s), with correct thinking switches and no CPU fallback. These synthetic checks do not establish a full-episode speedup.
