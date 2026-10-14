# ADR-0049: Compact DeepSeek wire text, preserve canonical evidence contracts

Status: accepted. Date: 2026-10-14.

Retry/context policy is superseded by [ADR-0050](0050-needed-data-for-all-model-checks.md): compaction now covers every provider, and rejected responses keep the minimal packet instead of restoring expanded input. Original cache/validation contracts remain immutable.

## Decision
The DeepSeek adapter uses a compact wire representation for recognized native selection-adjudication packets. It removes duplicated CURRENT ASR when exact unit text already covers it, duplicates of visual-neighbor speech covered by the longer speech context, repeated prior descriptions, technical unit-boundary metadata and redundant source-frame metadata. It retains unit IDs/bounds/text/frame ownership, CURRENT frame mapping, confirmed exclusions, questions, source image roles and context speech. Low-confidence ASR remains explicitly marked. Unrecognized packets and source-validation retries retain their full prompt.

The concise instruction retains source ownership, keep/drop coverage, concrete evidence, exact quote/frame grounding, action/causal constraints, confidence and uncertainty rules. All original images remain unchanged; this is not image resampling or a new verification pass. Repeated JSON schema nodes are factored with local `$defs` references and minified. Schemas with pre-existing references or anchors retain their existing scope. Expansion must equal the original schema exactly.

Canonical query inputs and the complete original schema remain the accepted-reply contract. Local validation uses that original schema and the unchanged native source validator. The adapter checks previous expanded request-body cache keys as well as the compact key. A rejected compact JSON response uses the existing retry budget with the expanded canonical prompt; a native source rejection also keeps its expanded repair request. Request diagnostics continue to hash the actual transmitted body.

## Validation and migration
Tests cover schema expansion, unchanged source facts/images, distinct or uncertain speech, fallback, old response-cache reuse and rejection of another unit's frame index. Twenty stored real packets showed a 38.2% reduction in UTF-8 text bytes; this is not a measured total-token or cost reduction. No provider requests are needed for this measurement.

Changing adapter code changes the existing stage identity. Reconstruct accepted stage snapshots offline through native validators under blocked provider dispatch; preserve current partial answers and canonical request signatures. Publish audited snapshots only to the owned stopped job with backups, then refresh the idle backend. Revert the adapter delta to restore the expanded wire format.
