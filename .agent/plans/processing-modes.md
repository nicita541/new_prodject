# Goal
Expose full montage, incremental montage and cached-analysis plan-only runs in Studio. Reuse source-owned checkpoints without overwriting previous jobs; rebuild invalid dependencies.

# Current state
Episode launch always creates an empty job. Retry reuses checkpoints inside that job. Semantic identities cover code and prompts but the aggregate analysis signature includes downstream planner components. Final analysis is saved in analysis-final.json. Exports and clean montage parts have validated fingerprints.

# Constraints
Preserve existing uncommitted changes, previous jobs and source media. All files and runtimes stay under F:/new_prodject. Old API calls keep full fresh-job behavior. Plan-only must never call a model, repair analysis, generate briefs or encode video. Inherited artifacts must remain within the owned source/episode boundary.

# Implementation
1. Add processing-mode contracts and source/episode-owned checkpoint inheritance, with explicit allowlists and independent copies.
2. Scope analysis signatures to upstream dependencies; keep real planner consumers in late-stage signatures. Record final snapshot provenance and validate plan-only prerequisites.
3. Add Studio mode choice, explanation and plan-only completion handling.
4. Add regression tests and document the contract/rollback.

# Validation
Use tools/python/python.exe -m pytest -q for processing, jobs, API, library, semantic-identity and quality-pipeline tests. Use tools/node/node.exe with frontend/scripts/check-studio.mjs (lint and smoke) and build-studio.mjs. No real inference or paid requests are necessary for contract tests.

# Risks and rollback
Cache transfer can be large; independent copies protect original jobs. Existing stage validators remain authoritative for incremental reuse. Plan-only deliberately freezes upstream analysis and fails if source/settings no longer match or quality requires repair. New modes default to full for legacy API callers; removing mode fields/UI restores prior behavior without deleting data.

# Progress
- [x] Mode contracts and checkpoint inheritance
- [x] Scoped signatures and plan-only path
- [x] Studio integration
- [x] Verification and documentation

Validated: 240 tests and 90 subtests passed across processing modes, DeepSeek, quality orchestration, semantic identities, jobs/API, analysis/provider, supplied ASR, production entry points, scene detection, final quality and clean parts. Studio syntax checks, bridge/DOM smoke tests and the native Studio build passed. `git diff --check` passed for touched tracked files. No real model inference or encoded-media run was performed.

The broader check exposed two existing tempfile-based provider tests blocked by Windows ACLs. Their fixtures now use the same ordinary workspace UUID directories as other repository tests; all seven provider tests passed afterward. No global installations or out-of-workspace outputs were used.
