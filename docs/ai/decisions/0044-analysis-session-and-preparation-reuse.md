# ADR-0044: Reuse local analysis models and overlap CURRENT preparation

Status: accepted. Date: 2026-10-14.

## Context
Independent stage contexts unloaded/reloaded the same local models five times per fresh analysis. Source hashing was duplicated across preparation consumers. CURRENT storyboard decoding blocked every scene/chunk request while the model was idle.

## Decision
`analysis` owns `AnalysisVisionSessions` for the complete call, including early cache returns and exceptions. The ordinary local route retains only the current model/projector/GPU configuration; a switch closes the old process before opening another. Boundaries and scene analysis share 4B; story, pacing/editorial and portrait framing share 9B. Thinking defaults switch only at sequential stage boundaries, while explicit request overrides and stage cache identities retain their previous values. Non-local/experimental transports retain their existing per-stage lifetime and routing. Model fallback behavior is unchanged.

`source_identity` owns a thread-safe, bounded in-process SHA-256 cache keyed by resolved path, size, mtime and ctime. The first use reads source bytes cooperatively and checks the stamp again before caching. No persisted digest seeds this cache. Analysis, processing, bounded storyboards, global verification and uncached focus/adjudication hashing use this owner. Image/log hashes remain independent integrity checks.

`scene_analysis` validates scene/chunk checkpoint ownership before scheduling images. `scene_preparation` has one worker and one outstanding CURRENT chunk, crossing scene boundaries and skipping valid decisions. Lookahead starts after foreground context preparation, immediately before the current model query. CURRENT windows are disjoint, so foreground recovery/legacy overview and lookahead cannot share an in-progress frame-cache key. Context, recovery, inference, progress, diagnostics and accepted decision publication remain on the coordinator. An exit signals cooperative cancellation and drains the worker before the provider session closes.

## Alternatives and consequences
Keeping both models loaded risks the 8GB GPU budget; parallel model calls change ordering and are unnecessary. Preparing whole scenes or all images ahead consumes unbounded resources. A persisted stamp-only hash cache weakens source verification across restarts. The chosen policy adds bounded preparation concurrency, preserves query inputs/order and avoids these costs. Helper code participates in semantic identities; existing semantic checks still determine checkpoint reuse after upgrades.

## Validation and rollback
Regressions cover load counts, thinking request bodies, close-before-open and error/cache-return cleanup, source mutation/concurrent hashing, ordered bounded lookahead, checkpoint reuse and actual FFmpeg source PTS. A synthetic local-model smoke verifies 4B/9B reuse and thinking switching separately from full-episode performance claims. Restore only these task-specific source changes to return to independent sessions/synchronous preparation; no data migration or persisted state removal is needed.
