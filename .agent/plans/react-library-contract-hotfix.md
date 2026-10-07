# Goal

Fix the React library runtime regression against the existing backend contract, verify the five real screens and commit separately, then resume the incomplete semantic montage Stage 2.

# Current state

React assumes nested project episodes, a separate trash payload and string job IDs. Library.snapshot returns flat projects/episodes and object job references. Both archive and restore return id/archived. Legacy uses archived_at and hides individually archived episodes whose parent is archived. Main remains untouched; current branch is codex/dramatic-montage. Previous montage work is preserved in the current user commits; raw003 finished unresolved after 23 actual model requests.

# Constraints

Preserve backend and legacy behavior. All dependencies, generated files, caches and evidence stay under F:/new_prodject. Do not launch paid/model jobs or mutate the existing library for a smoke check. Test archive/restore using isolated backend data. Keep the hotfix separate from the pending montage fixes.

# Implementation

1. Audit every React-used request/response against server/library and supporting public response functions.
2. Align raw API types and create shared selectors for active/archived ownership, job references and delete locks.
3. Repair Projects/Episodes/Edit/Review/Trash, including completed-only review and snapshot-based active job choice.
4. Replace false mocks with one realistic flat fixture and a backend-generated contract fixture; add regression tests.
5. Run lint/build/frontend tests/backend routing+library checks/diff check. Start the real app and inspect all five screens against its actual library and legacy.
6. Commit the hotfix; resume the unfinished Stage 2 source-index-domain fix and subsequent stages without restarting.

# Validation

Use package scripts with the workspace Node runtime and workspace npm cache. Generate contract data through the real Library.snapshot using isolated temporary state. Request actual GET /api/library, save local evidence, compare React and legacy counts/job IDs/trash. Never claim unexecuted checks passed.

# Risks and rollback

Archived parents hide their child episodes without individually archiving them. Preserve this rule and running/queued locks. Ignore stale asynchronous job responses after route changes. Revert the isolated hotfix commit to restore its previous frontend only.

# Progress

- [x] Read instructions and backend/legacy contract; reproduced mismatched types and consumers.
- [x] Correct raw types/selectors/screens and all API discrepancies.
- [x] Realistic/backend-generated fixtures and regression protection.
- [x] Full requested checks and real five-screen verification: 762 Python, 4 routing pytest, 78 React, 24 legacy UI; build/lint/diff passed. See docs/react-library-contract.md for actual library screen evidence and lint warnings.
- [x] Separate hotfix commit/report and resume montage Stage 2: 72034c638ec2ac4733f5715632e6fbf515c9f733. Returned to the source-index-domain bug in multi-page global selection, with the earlier Stage 2 work preserved.
