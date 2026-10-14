# Review only candidate montage fragments

## Goal
Economy mode reviews candidate montage fragments and required context, dispatches recovery only for unresolved candidates, and reuses matching accepted work. Unselected original footage stays available in the source catalog without becoming approved for export.

## Current state
The economy switch skips five optional passes. Selection adjudication still covers every unit in each original parent scene. Story/dialogue providers already use selected ranges, but those ranges precede final planning. The current job is stopped with seven accepted full passes and206 accepted DeepSeek replies. Preserve that state.

## Constraints
No production restart or inference during development. Preserve native positive-proof, source-unit, dialogue, word and export gates. Draft planning must remain non-exportable and cannot manufacture accepted confidence or exclusion claims. Use real source units, whole utterances and dependency closure; keep original source bounds/catalog and provenance. Actual episode duration must survive filtering. Work in the isolated source copy and verify integration baselines.

## Implementation
1. Add an explicitly non-exportable deterministic draft plan using current candidate geometry and ordinary planning rules, while retaining strict final planning defaults.
2. Derive bounded CURRENT fragments from real units overlapping draft cuts; include required event dependencies and word context. Project source records into complete contiguous unit windows, preserve original unit IDs, and prepare only their actual source collages.
3. Restore the longest matching accepted full-pass prefix before projection. Mark those passes reused in the owned coordinator; run remaining native passes only on candidate windows. Retain genuine per-query cache matching and downstream recovery gates.
   Following the user's clarification, route the existing credit continuation, title, closing-novelty and source-role callbacks only to detected regions with five-second whole-unit context. Do not add a model pass. Skip unaffected specialist calls and dim them as not needed. The existing credit classifier honors the same targets; native selection adjudication still responds to concrete problems or missing evidence.
4. Carry actual episode duration to selective story/credit/closing callbacks. Update processing hints and scope counts. Keep full mode available.
5. Audit/reconstruct existing accepted contracts offline after the additive routing change, integrate and refresh the idle server. Leave the user's job stopped.

## Validation
Test non-exportable drafts, word-safe/source-owned windows, dependency closure, gaps, selected-unit dispatch, untouched unresolved gates, truthful duration, accepted prefix reuse, changed candidate cache invalidation and full-mode compatibility. Run portable backend and existing frontend checks. Compare candidate/source unit counts on the stopped real job without inference.

## Risks and rollback
Initial source discovery still examines the video to find candidates. Draft choices are provisional and may retain necessary context beyond final cuts. No claim is made that unreviewed footage is filler. Disable economy for original full-source review. Preserve original source catalogs, cache banks and migration backups.

## Progress
- [x] Identified full-parent unit adjudication as unnecessary request fanout.
- [x] Implemented draft scope, projection and accepted-prefix reuse.
- [x] Verified and integrated; current job remains stopped.

Implementation and the clarified existing-check routing are integrated after baseline hash verification. Isolated suite passed 230 tests and 68 subtests; closing/progress suite passed 71 tests and 40 subtests. Frontend build, syntax lint and bridge/DOM smoke passed. Real stopped-source measurement reserves 925 of 1063 units in 152 windows from 129 original events, including specialist boundary context; each specialist receives only its own target windows.

Completed: fixed bounded inheritance of verified story and parent sequence proofs, and protected original storyboards with unique cropped-window IDs. The final main suite passed 125 tests and 55 subtests. The final DeepSeek dry run restored seven accepted stages, made zero new dispatches and stopped before the first unmatched scoped request. Specialist inputs: credits 101 units, titles 166, closing 35 and source roles 101; these are not request/token counts. Seven native-validated snapshots and 711 changed cache files were published with stage/control and native-cache backups. Fresh Product ownership checks confirmed the updated Studio backend/UI, idle health, DeepSeek provider, economy enabled, continuation enabled with cache_only false, and the original job still cancelled. No production inference was resumed. See scratch/needed-fragment-report.md and scratch/needed-fragment-live.json.
