# ADR-0037: Immutable finishing inputs and verified playback selection

## Status
Accepted.

## Context
Queued finishing workers used live plan/caption files. Editing from another client could change only later parts of a single export. Current playback also promoted legacy finishing files without proof of their source plan and failed globally on one corrupt export record. Episode settings and finishing maintained inconsistent appearance drafts and previews.

## Decision
Studio remains the mutation owner. Under its existing manager mutex, finishing submission clones the profile, selected plan parts and effective job-scoped captions. The worker renders those resolved parts without rereading captions or the plan. Status records retain the original source-plan digest and caption revisions for provenance. Original media is not duplicated or replaced. Pending snapshots live with the owned thread; interrupted tasks require a fresh submission after restart.

Caption edits remain available to other clients. Blocking them for an entire render was rejected because it prevents preparing subsequent changes; live reads were rejected because they produce inconsistent exports.

Only completed registered exports carrying a matching source-plan digest may become current playback/download files. Malformed registry/status records and malformed file entries are skipped with local diagnostics. A missing digest supplies no provenance: legacy files keep their explicit export links but are not automatically promoted. A failed/partial export leaves original or previously verified files available.

Avatar assets are immutable canonical PNGs under `finishing/avatars`, with episode-owned opaque IDs. The renderer multiplies the image alpha by its round mask. Video profile validation and HTTP upload bounds remain authoritative.

The browser rebases clean appearance fields against the shared profile while preserving explicit unsaved fields. Meaningful changes invalidate baked previews; a revision counter prevents a pending older preview from replacing newer edits. Reopened finishing videos use source cuts after a finishing export so baked cards/captions are not reused as editing inputs. Phone and finishing canvases share the same browser geometry, matching the raster renderer.

Export submissions accept 1–100 unique part IDs, aligning the caption/style domain and allowing one complete montage transaction instead of partial 50-part batches. Queue and worker concurrency limits are unchanged. Known old episode hash URLs are translated to current query routes at startup.

## Compatibility and rollback
Existing profile defaults, original job outputs, original plans/ASR, stored captions and uploaded assets remain intact. Older exports are still downloadable by explicit ID. No migration rewrites user media or legacy status files. Reverting the selection/UI changes restores the previous presentation behavior; retained original files provide the fallback. Backup includes both `data/jobs` and root `finishing`.

## Validation
Regression tests cover queued snapshot isolation across actual threads, safe selection with mixed corrupt/legacy/valid records, transparent avatars, the larger bounded request, clean versus dirty appearance drafts, stale and pending previews, old hash links and the post card CSS. Repository-native build/lint/smokes and the complete Python suite provide technical validation. Editorial quality requires separate source-versus-output review.
