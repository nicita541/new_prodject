# Goal
Keep the user's Studio Edition as the only application interface. Remove shipped sample catalogs, generated demo plans/media and mock API implementations; consolidate identical helpers and give analysis, editorial finalization, quality inspection and recovery explicit owners.

# Current state
Studio public assets contain unused reference/mock implementation mixed with live code. React src and app/static provide secondary interfaces; Vite builds the React shell while copying Studio. Analysis owns both orchestration and finalization; final_quality owns inspection and recovery, calling analysis back. Several source-text/hash/cancellation helpers have identical bodies.

# Constraints
Do not cancel, restart or relaunch the active job/backend/official CLI. Preserve real catalog, media, models, successful response caches and the user's untracked log collector. Preserve native validation and provider behavior. Tests may contain explicit isolated fixtures; they are never application/demo data. Running Python retains loaded functions: retain import aliases needed by the active pipeline, with one implementation per function. No frozen or forged cache identities; subsequent source changes legitimately invalidate affected caches.

# Implementation
1. Delete product demo initialization/media/mock routes; initialize an empty server-owned UI store. Adapt existing UI integration checks to explicit test-owned records.
2. Remove React/legacy/reference interfaces and their dedicated fixtures/tools/tests. Build only Studio with a small Node static builder; retain jsdom only for real Studio integration tests. Update startup/setup/check commands and HTTP routes.
3. Extract editorial finalization, result assembly and quality recovery into named modules; pipeline coordinates, final_quality inspects only. Keep single-function import aliases for the current loaded process.
4. Consolidate only AST-confirmed identical helpers with identical signatures/semantics. Cover shared dependencies in semantic identities and validate cancellation/source matching.
5. Update stable architecture, affected docs and ADR, run repository checks, inspect real UI and commit on the current branch.

# Validation
Existing production entrypoint/route tests, Studio exact/bridge Node integration checks, all relevant Python analysis/quality/provider/planner/cache tests, Node syntax/build/lint. Verify the active job and CLI remain unchanged/running throughout; do not claim a new backend deploy.

# Risks and rollback
UI initialization/tests previously rely on seeded records; move records into test setup only. Old routes become unavailable on next backend start. Hot imports in the active pipeline need preserved aliases. Source refactoring changes cache identities legitimately; do not erase checkpoints. Git reverts restore individual stages.

# Progress
- [ ] Studio-only UI and build
- [ ] Explicit pipeline boundaries and shared helpers
- [ ] Validation, docs, review and commit
