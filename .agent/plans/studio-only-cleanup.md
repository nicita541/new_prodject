# Goal
Keep the user's Studio Edition as the only application interface. Remove shipped sample catalogs, generated demo plans/media and mock API implementations; consolidate identical helpers and give analysis, editorial finalization, quality inspection and recovery explicit owners.

# Current state
At the start of cleanup, Studio public assets contained unused reference/mock implementation mixed with live code. React src and app/static provide secondary interfaces; Vite builds the React shell while copying Studio. Analysis owns both orchestration and finalization; final_quality owns inspection and recovery, calling analysis back. Several source-text/hash/cancellation helpers have identical bodies.

# Constraints
Latest user instruction: no run is active. Do not launch user video processing during cleanup. Preserve real catalog, media, models, successful response caches and the user's untracked log collector. Preserve native validation and provider behavior. Tests may contain explicit isolated fixtures; they are never application/demo data. Coordinators import single implementations from their owners; migrate every internal consumer and test. No frozen or forged cache identities; subsequent source changes legitimately invalidate affected caches.

# Implementation
1. Delete product demo initialization/media/mock routes; initialize an empty server-owned UI store. Adapt existing UI integration checks to explicit test-owned records.
2. Remove React/legacy/reference interfaces and their dedicated fixtures/tools/tests. Build only Studio with a small Node static builder; retain jsdom only for real Studio integration tests. Update startup/setup/check commands and HTTP routes.
3. Extract editorial finalization, result assembly and quality recovery into named modules; pipeline coordinates, final_quality inspects only. Migrate recovery imports directly to the owning module.
4. Consolidate only AST-confirmed identical helpers with identical signatures/semantics. Cover shared dependencies in semantic identities and validate cancellation/source matching.
5. Update stable architecture, affected docs and ADR, run repository checks, inspect real UI and commit on the current branch.

# Validation
Existing production entrypoint/route tests, Studio exact/bridge Node integration checks, all relevant Python analysis/quality/provider/planner/cache tests, Node syntax/build/lint. Do not launch a new user job or cloud CLI; checks use isolated fixtures.

# Risks and rollback
UI initialization/tests previously rely on seeded records; move records into test setup only. Old routes become unavailable on next backend start. Hot imports in the active pipeline need preserved aliases. Source refactoring changes cache identities legitimately; do not erase checkpoints. Git reverts restore individual stages.

# Progress
- [x] Studio-only UI and build
- [x] Explicit pipeline boundaries and shared helpers
- [x] Validation, docs and review
- [x] Commit on codex/dramatic-montage (recorded in Git history)


# Verified outcome
Full Python suite: 1394 passed and 630 subtests passed in 201.63 seconds. Both Studio Node/jsdom checks, syntax lint and native build passed. After JavaScript formatting, 12 production-entrypoint/route checks passed again. AST comparison confirms the three moved orchestration/result/recovery algorithms are unchanged apart from imports of their new owners. CI YAML parses successfully. The production status API now ignores malformed non-string diagnostic stages; its existing regression and all API checks pass. No user montage, cloud query or backend restart was launched.
