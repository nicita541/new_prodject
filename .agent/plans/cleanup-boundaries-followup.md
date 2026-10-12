# Goal
Finish the confirmed leftovers from Studio cleanup: remove obsolete code and styles, give file persistence, media delivery and source-range calculations a single owner, and eliminate analysis-facade back imports.

# Current state
Only Studio is shipped, but legacy review handlers/styles remain. Media helpers, story validators and storyboard functions are still imported through analysis; shot detection calls that coordinator back. Three JSON writers and identical range/cache helpers overlap. Finishing imports the HTTP application to stream files.

# Constraints
Work on codex/dramatic-montage. No user video runs, agy calls, backend restart, catalog deletion or checkpoint deletion. Preserve algorithms, provider choices, JSON encodings and missing/corrupt file handling. Test-owned fixtures stay isolated. Source identities reflect real dependencies; never freeze hashes.

# Implementation
1. Introduce json_store, source_ranges and http_media owners and migrate consumers.
2. Consolidate stable cache data/digests; remove obsolete analysis windows and facade imports/back edges.
3. Remove unreachable legacy review actions and selectors, preserving the current player and selection behavior.
4. Document ownership and enforce meaningful dependency/persistence regressions; validate and commit.

# Validation
Focused jobs/media/cache/analysis/routing checks, full Python suite, existing Studio Node integration checks, lint and native build. Compare moved algorithm ASTs and cache digest/output encodings.

# Risks and rollback
Monkeypatches must target the actual owner after migration. Preserve the analysis writers' historic NaN encoding option explicitly while state JSON remains strict. Prune only proven unused legacy review selectors. Revert the cleanup commit to restore the old layout; real user data are untouched.

# Progress
- [x] Shared owners and consumers
- [x] Obsolete facade and review code
- [x] Documentation and regression checks
- [x] Validation and commit

# Verified outcome
Full Python suite: 1397 passed, 630 subtests passed in 203.60s. Studio bridge/exact jsdom checks, lint and native build passed. Moved range/provider/media algorithms and stable cache filtering preserve their ASTs; historic digests and JSON encoding contracts checked. No exact repeated top-level function bodies of at least 24 AST nodes remain in app (not a claim about all semantic similarity). All app modules are linked in the module inventory. The retired UI-view launcher alias was removed after this run; 13 final startup/route checks passed separately. No user video run, cloud query or backend restart occurred.
