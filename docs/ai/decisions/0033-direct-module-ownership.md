# 0033 — Direct ownership of utilities, routing and media delivery

Status: accepted, 2026-10-13.

## Problem

After Studio-only cleanup, utility calls still travelled through analysis, and media_probe/vision imported that coordinator back. Finishing imported server to obtain byte-range streaming, creating a dependency on application composition. JSON writing, source-range algebra, spaced hashes and stable cache payload normalization had multiple implementations. An obsolete simulation script contained an alternative planner with incompatible defaults.

## Decision

Use direct imports from the actual owner. `json_store` owns durable JSON operations; its encoding partials preserve the existing strict state, permissive analysis and compact snapshot contracts. `source_ranges` owns merge/intersection and the existing ordered subtraction algorithm. `content_identity` owns digest encodings and removal of operational cache flags from semantic data. `http_media` owns streaming already-approved files. `analysis_provider` owns provider settings/identity and mandatory model files; `vision` owns all model sessions, including manual9B routing.

Delete unused fixed analysis windows, the unused cut-time projection, the alternative simulation planner, unreachable former-review actions and proven unused rv- CSS selectors. Retain shared player styles and the current rv2 review. Correct its selected-card scrolling. Tests import and patch owning modules rather than a compatibility facade.

## Alternatives and consequences

Keeping facade imports would preserve cyclic dependencies and let test hooks hide the real call graph. A broad rewrite of inference or planning would change behavior unnecessarily. Instead, algorithms move unchanged where possible, and every consumer migrates in this commit. Different domain validators with different normalization rules remain separate; naming similarity alone is not evidence of duplication.

No API schema, provider algorithm, FFmpeg scene algorithm or source timestamp contract changes. Old data are retained. Extracted dependencies participate in real semantic cache identities, which can invalidate affected stage caches rather than silently reuse incompatible decisions. Persistence now has unique temporary paths and bounded Windows-lock retries for all encodings.

## Validation and rollback

Existing model-routing, analysis/cache, range, HTTP range/finishing, planner and Studio integration tests protect the data flow. Added checks cover utility dependency direction, failed/concurrent atomic publication, preserved JSON encodings and actual current-card scrolling. Revert this commit to restore prior module locations; no user-data migration is required. [Ownership index](../../../app/README.md).
