# Goal
Add a review assistant beside montage playback. The user reports an opening left in a part or clipped speech; the worker interprets source-bound feedback, repairs the cached analysis/plan and creates a new independently reviewable version.

# Current state
Review has a source timeline and part selector. Processing supports source-owned checkpoint inheritance and frozen analysis snapshots. Production sequence validators establish original OP boundaries/anchors; source-proved speech handles and final quality validation guard edits. Worker owns inference, cancellation, recovery and exports.

# Constraints
Preserve current uncommitted work and original completed versions. HTTP reads never infer. Free text cannot supply arbitrary source timestamps, paths or shell instructions. Repairs use bounded supplied part IDs and original evidence; uncertain or unsupported requests produce an explicit clarification. All task artifacts/runtimes stay in the workspace. No paid or real model calls are needed for implementation tests.

# Implementation
1. Add validated/idempotent feedback submission, immutable request provenance and version-linked history in job storage.
2. Interpret feedback into bounded opening/speech actions; independently review opening boundaries and increase source-bounded speech margins only for affected intervals. Persist correction status/replies.
3. Run corrections through cached analysis, ordinary replanning and final quality/export gates; use per-part render identity to reuse unchanged outputs.
4. Add the review assistant panel, message history, progress and corrected-version link without interrupting playback.
5. Verify worker/API/security boundaries, corrective mechanisms, cache reuse and Studio DOM/build. Document the supported scope and rollback.

# Validation
Use portable Python pytest for feedback, processing, production sequences, speech handles, quality pipeline, jobs/API and stage progress tests. Native Node Studio lint, DOM/bridge smoke and build. Authored test media/providers do not establish real inference/encoding quality.

# Risks and rollback
Model interpretation is constrained to supplied part IDs and supported actions. OP removal retains existing independent proof rules; unsupported/uncertain cases stop without claiming repair. Increased margins cannot cross confirmed exclusions or include an omitted word. Corrective replanning may shift part boundaries; version history preserves comparison. New per-part fingerprints invalidate old global checkpoints once. Remove feedback controls/routes to disable the feature without removing data.

# Progress
- [x] Storage/API contract
- [x] Correction mechanisms and pipeline
- [x] Review UI
- [x] Verification and documentation

Verification: 284 tests and 56 subtests passed across feedback, processing, quality, production, speech, retention, API/jobs, semantic identity, source entrypoints, clean parts, story and export mechanisms. After ownership/archive changes, the focused 97-test suite (13 subtests) passed again. Studio lint, bridge/DOM smoke and native build passed; DOM coverage includes preserved playback, escaped comments, scoped context, replies and corrected/original version navigation. Diff whitespace checks passed. All provider/media tests are authored stubs; no real inference, paid requests or actual encoded series were run.
