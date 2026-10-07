# Goal

Implement the four-stage semantic montage plan on `codex/dramatic-montage`: factual shots, semantic scenes and word-safe units; uncertainty recovery and independent visual verification; adaptive episode profiles and budgets; natural arcs, minimal bridges and complete cache/decision diagnostics.

# Current state

Starting HEAD `5ee376f5781164648cff4b0d9f616ec6c64ed7a7`. Baseline: 456 unittest tests pass. Initial unstaged server/UI/API-test changes belonged to other work and were excluded from stage 1–3 commits. The user subsequently preserved those changes and the stage 4 core implementation in commit `6d16060577cf2a0381876bf7573df7cff4dcbf58` (`11`). The final completion commit builds on that user commit without rewriting it. Originally `analysis.analyze` created events from roughly forty-second ASR windows, `candidate_units` ignored visual boundaries inside speech, adaptive shot suppression discarded raw candidates, and dramatic planning used a fixed 520-second target and preferential exact part count.

# Constraints

All runtime files, temporary files, caches and dependencies stay inside `F:/new_prodject`. No changes to main. Preserve source audio, factual source timestamps, source exclusions, paid-provider accounting and existing pipeline contracts. Do not automatically run paid analysis or expose credentials. Each completed stage receives regression tests, a separate commit and a report. Existing job artifacts must not silently authorize stale semantic decisions.

# Implementation

1. Validate baseline and fix demonstrated analysis error handling. Introduce semantic-scene module/checkpoint, preserve technical chunks under one scene, word-safe visual units, context-only neighbors and evidence-rich storyboard. Add unified pipeline diagnostics and stage-1 regression coverage.
2. Separate confidence dimensions, automatic fresh recovery, bounded safe uncertainty fallback and visual global corrections with retained provenance. Record local/recovery/global/final understanding.
3. Retain raw/accepted/suppressed shot evidence, derive montage profile and scene settings, replace fixed retention quota with a material-specific range.
4. Build arcs before part grouping, interpret dependencies as bounded contextual signals, validate selected continuity, add minimal safe bridges, prefer natural part counts and endings, fingerprint component policies and prompt text, persist planner decisions and long synthetic regressions.

# Validation

Use bundled Python: `tools/python/python.exe -m unittest discover -s tests -q`. Run focused new and affected modules at every stage and full suite before each commit. Use `tools/node/node.exe --test --test-isolation=none tests/test_ui.cjs` for baseline/UI compatibility. Run synthetic end-to-end analysis/planning flows without paid calls. Inspect produced diagnostics and, where practical, render a local synthetic video to verify factual frames and word safety. Real model quality remains a separately stated limitation unless exercised.

# Risks and rollback

Visual heuristics are evidence, not calibrated probabilities. Preserve uncertainty/evidence and cache versions; no invented actions. Word-safe boundaries may shift slightly from a camera cut. Recovery costs more inference, so checkpoint each accepted result. Revert a stage commit to restore behavior; source files and factual ASR remain intact, derived decisions recompute under the older component signatures. Integrate subagent detector changes only after reviewing its tests and actual production feature extraction.

# Progress

- [x] Read attached requirements, check branch/HEAD/worktree, baseline tests.
- [x] Stage 1 committed as `52ce612`: 493 Python tests, 23 UI tests, real FFmpeg scene/action-frame integration.
- [x] Stage 2 committed as `e340521`: 536 Python tests and 23 UI tests.
- [x] Stage 3 committed as `550af11`: 566 Python tests and 23 UI tests.
- [x] Stage 4 implemented and verified: 622 Python tests, 23 UI tests, complete source-interval audits and saved long synthetic planning diagnostics. Core implementation is preserved in user commit `6d16060`; final audit fixes/documentation receive a separate completion commit.

Baseline UI fixes committed separately as `1eb2d9c`: progress scaling and visible processing messages. Stage 1 uses at most 96 requested frames per technical chunk and bounded neighbor pages; the existing story refiner consumes these children and merges evidence back under the original semantic parent.

Stage 2 adds strict semantic/visual/context confidence, fresh dense-frame recovery, word-safe minimal fallback and an independent visual verification checkpoint. Confirmed source exclusions remain authoritative. Original, recovery and global decisions are preserved even when a later decision corrects the summary.

Stage 3 preserves all FFmpeg candidates above the base 0.14 threshold, including suppression provenance. Real descriptors probe suppressed boundaries and retain original shot IDs. Initial/refined episode profiles adapt grouping and source-bounded budgets; the planner measures actual retained material. A real FFmpeg regression recovers a suppressed location change inside one accepted shot.

Stage 4 builds arcs before selection, shares bounded continuity across planners, protects dialogue/action boundaries, compares alternative part counts and partitions all source intervals into explained decisions. Component signatures cover actual prompt text and policies in outer and nested checkpoints. The committed core passed 617 Python tests. The requirement audit then added explicit neighbor-recovery coverage, missing question/answer rescue under quota, the complete diagnostic catalog, post-level durations and cache-safe uncertainty counters. The independent review agent stopped at a service usage limit; final review and verification are completed by the coordinator.

Final validation: `tools/python/python.exe -m unittest discover -s tests -q` ran 622 tests successfully; `tools/node/node.exe --test --test-isolation=none tests/test_ui.cjs` ran 23 successfully; `git diff --check` passed. Saved 1,440-second fixtures explain all source intervals: kidnapping retains 68 seconds with two exact bridges; five arcs retain 420 seconds in five parts despite a preferred count of six. Requirement mapping and per-stage/final reports are in `scratch/semantic-montage-*-report.md` and `scratch/semantic-montage-completion-audit.md`. No production vision-model episode-quality claim is made.
