# ADR-0048: Review candidate montage windows in economy mode

Status: accepted. Date: 2026-10-14.

## Decision
Economy mode builds a deterministic, explicitly non-exportable draft before the remaining editorial checks. `review_scope` maps its cuts to whole original source units, adds prerequisite events and causal unit context, and projects contiguous CURRENT windows. Original IDs, bounds and catalog remain recorded under `review-scope/`; unselected footage is not classified as filler or approved for export. Full mode retains the existing full-source route.

The longest exact accepted full-pass prefix is restored before projection, retaining producer provenance. Those completed passes are not repeated on cropped windows. Subsequent native story, selection, dialogue and framing checks receive only candidate windows; exact individual replies and normal unresolved-only recovery remain reusable. Actual episode duration is passed separately so removing late footage cannot make an earlier window look like the episode ending. Planning preferences and scope policy participate in final cache identity.

Draft planning bypasses only final semantic readiness and allows zero-priority excluded candidates; it retains source geometry and whole-word validation. Drafts cannot be exported. Final planning preserves all semantic gates, bounds speech handles to reviewed windows, and rejects cuts outside them. Cropped windows discard whole-parent state and out-of-window relationships. No new dependency or provider transport is introduced.

Existing specialist checks also use first-pass hints rather than scanning every candidate scene. Detected opening/ending/credit/title regions reserve five seconds on each side, expanded to whole existing source units. Windows split when their required specialist set changes. Existing credit continuation, title, closing-novelty and source-role callbacks receive only their target windows. A source-role failure requests its existing retry. The existing credit classifier inside story refinement also honors these regions. A normal scene's position or silence alone no longer triggers every specialist in economy mode. Missing hints preserve source footage rather than manufacturing an exclusion; full mode retains broad scanning.

No model check is added. Native selection readiness already dispatches adjudication only for actual problems, including missing positive source proof; those requirements remain. Skipped specialists are shown dimmed as `Не потребовалось`. Targeted rows display the selected fragment count. Cropped collages use unique window IDs expected by native callbacks and never overwrite original parent evidence. Source-qualified parent sequence proofs keep their original boundaries in window provenance; only their validated overlap is inherited as an exclusion. Verified story ranges are bounded to CURRENT without inventing a new sequence-boundary claim.

## Limits and migration
Initial perception still surveys the source to discover candidates. The provisional balanced draft and its necessary context may include more footage than the final montage, including when the final profile is dramatic. There is no fixed token-saving percentage. Invalid unit coverage or dependencies fail explicitly instead of silently reviewing everything. Original source catalogs, accepted replies and provider banks remain available.

Existing accepted legacy contracts require explicit offline source/answer validation after orchestration hashes change; native cache signatures are never relabeled. Offline reconstruction blocks new model starts and network requests. Publishing audited completed stages does not resume a stopped job. Disabling economy restores the full route; backups and original banks provide rollback.

## Validation
Regression coverage checks selected-unit dispatch, dependency closure, whole words, non-exportable drafts, unchanged unresolved flags, rejected out-of-scope export, prefix reuse and candidate cache invalidation. The stopped episode is also reconstructed offline with both providers to verify retained work without paid requests.
