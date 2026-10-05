# Automatic context for short covers

## Goal
Every finished short automatically has a brief Russian synopsis and a copyable image prompt in the review screen, including future montages.

## Current state
Plans contain chronological cuts, remapped subtitles and model-generated event summaries. Review already loads the plan and switches selected parts. Existing completed videos need no re-render.

## Constraints
Stay on the development branch and inside the workspace. Preserve cuts, subtitles, export fingerprints and MP4s. Use the selected analysis provider; opening a review must not start inference or remote requests. Exclude summaries of events crossing a part boundary to avoid leaking another part's events. Model failure must not prevent exporting a video.

## Implementation
1. Add bounded, validated generation and signed per-part caches from final cuts, selected dialogue and six current source frames; provide an extractive fallback. Inspection exposed incorrect speaker names in legacy event summaries, so generation uses unassigned dialogue and current frames with a setup-focused brief rather than retelling attributed exchanges.
2. Run generation automatically after planning. Derive fallback context for legacy plan responses without modifying video or making requests.
3. Show context for the selected part with a copy button, backfill the latest completed montage through the same generator, and verify the flow.

## Validation
Test selection of evidence, rejection of malformed answers, cache invalidation/reuse, failure/cancellation, API compatibility and part switching/copying. Run the repository Python and Node checks, inspect all eleven generated briefs, and verify the browser UI.

## Risks and rollback
Short creative summaries can still misinterpret ASR or source summaries. Label fallback text and keep it grounded in existing evidence. Remove the optional metadata/generation/UI integration to roll back; exports remain unchanged.

## Progress
- [ ] Automatic generation and integration
- [ ] Review UI and compatibility
- [ ] Tests, latest montage backfill and browser verification
