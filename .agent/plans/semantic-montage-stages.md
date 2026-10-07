# Goal

Implement the four-stage semantic montage plan on `codex/dramatic-montage`: factual shots, semantic scenes and word-safe units; uncertainty recovery and independent visual verification; adaptive episode profiles and budgets; natural arcs, minimal bridges and complete cache/decision diagnostics.

# Current state

Starting HEAD `5ee376f5781164648cff4b0d9f616ec6c64ed7a7`. Baseline: 456 unittest tests pass. Existing unstaged server/UI/API-test changes belong to other work and must remain outside stage commits. `analysis.analyze` creates events from roughly forty-second ASR windows. `candidate_units` ignores visual boundaries inside speech. Adaptive shot suppression discards raw candidates. Dramatic planner uses a fixed 520-second target and preferential exact part count.

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
- [x] Stage 3 implemented and verified: 566 Python tests and 23 UI tests; separate commit follows.
- [ ] Stage 4 implemented, verified and committed.

Baseline UI fixes committed separately as `1eb2d9c`: progress scaling and visible processing messages. User's original server/UI/API changes remain unstaged. Stage 1 uses at most 96 requested frames per technical chunk and bounded neighbor pages; the existing story refiner consumes these children and merges evidence back under the original semantic parent.

Stage 2 adds strict semantic/visual/context confidence, fresh dense-frame recovery, word-safe minimal fallback and an independent visual verification checkpoint. Confirmed source exclusions remain authoritative. Original, recovery and global decisions are preserved even when a later decision corrects the summary.

Stage 3 preserves all FFmpeg candidates above the base 0.14 threshold, including suppression provenance. Real descriptors probe suppressed boundaries and retain original shot IDs. Initial/refined episode profiles adapt grouping and source-bounded budgets; the planner measures actual retained material. A real FFmpeg regression recovers a suppressed location change inside one accepted shot.
