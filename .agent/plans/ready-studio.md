# Goal
Deliver a usable Russian local studio: launch, import episode, choose a clear visual preset, generate chronological shorts with readable captions, preview/download results. Validate the real supplied episode with the funded DeepSeek account.

# Current state
Portable components are ready. Existing loopback FastAPI UI and checkpointed pipeline work, but the latest DeepSeek-plan job was cancelled during expensive local framing; the first export failed quality review. Current free account check confirmed USD 2.03. The two supplied YouTube examples were opened: outlined compact captions and a blurred portrait background are useful references.

# Constraints
All files/caches/process logs stay in F:\new_prodject. Retain original audio and chronological story; do not invent dialogue. Paid calls use existing accounting/cache. Preserve existing jobs and their default portrait/classic output. No dependencies or global installs.

The user clarified USD 0.10 per processing attempt, requested resetting the current counter, reported clipped dialogue in parts 4–6, and requested an original-source timeline with retained/removed clips and playback. Charges and unknown-request replay guards must survive attempt reset. Dialogue within a retained story scene must remain complete.

# Implementation
1. Persist validated per-job layout/caption options; missing settings preserve legacy output. Keep story cache independent of rendering layout; whole-frame layout skips unnecessary AI cropping.
2. Add a whole-frame blurred-background composition and short accent captions. Include options in render fingerprints.
3. Simplify Russian controls, visual preview, drag/drop and result navigation; launch only after server is ready and reuse an existing server.
4. Validate tests, actual browser interactions and real episode output; inspect contact sheets and audio timing. Sync affected docs.
5. Reproduce dialogue loss: ASR-edge cuts removed audible tails (source VAD confirms 0.30–0.43 seconds in checked parts); model range selection omitted replies in retained events. Add bounded 0.55-second speech tails/0.18-second leads, restore retained-story speech, version the planner and rebuild from cached analysis.
6. Display exact original-source intervals, per-part assembly offsets and omitted gaps. Serve only the stored contained source through loopback range streaming. Compare retained/removed clips in a second player.
7. User rejected the landing-page appearance. Replace it with a compact editing workspace: source/settings and history on the left, preserved single timeline/source player in the center, export preview and parts on the right. Keep real controls, job identity, disclosures and budget behavior. Verify wide and narrow layouts.

# Validation
Portable Python pytest command documented in project-context; existing Node UI suite. Add meaningful checks for option persistence/rejection, cache isolation, complete source composition and actual ASS rendering. Exercise launch, import, generation, playback and downloads on loopback. Record real episode evidence separately.

# Risks and rollback
Story/ASR can still make mistakes. Preserve source/checkpoints/old outputs and document observed quality. Layout is a named preset rather than an arbitrary FFmpeg expression. Old API callers and jobs retain defaults. Revert new options to portrait/classic to restore original rendering.

# Progress
- [x] Inspect current pipeline and references; confirm funding.
- [x] Persist options and implement presets.
- [x] UI and launcher (actual cold start through the one-click batch).
- [x] Per-attempt budget and explicit reset; real UI counter renewed without erasing charges.
- [x] Dialogue-tail reproduction and correction; retained-story transcript coverage checked.
- [x] Timeline code, source streaming and regression checks.
- [x] Tests and real episode review (technical checks and documented editorial limits).
- [x] Documentation and handoff.
- [x] Studio workspace redesign and responsive browser verification.

First full-frame/accent export completed 12 parts. Technical decoding/audio correlation checks and cache-only repeat passed; contact sheets showed readable captions but long silent context and retained title/closing material. User review identified dialogue defects, so this export is preserved under previous_exports/before-dialogue-fix and is superseded by the corrected 13-part export. Do not imply editorial acceptance merely from successful export.

Final validation: Python 274 tests + 103 subtests passed; the updated Node UI suite passed all 11 checks. Final 13-part exports decoded successfully with chronological contact sheets and source-audio comparisons. Eight dialogue-tail/recovered-reply excerpts had correlation >=0.97688 and best lag 0ms. Confirmed opening interval 157.53–183.30 is absent from the final plan. Cache-only repeat took 1.094s with external Python connections forbidden, no attempted external connection, and identical private-ledger hash. Current attempt 4 has $0 usage / $0.10 allowance; cumulative job estimate remains $0.0765117.

Design direction: graphite #101217, panel #191c23, separators #303642, text #eef1f6, muted #a0a9b8, control accent #a8c5ed; preserve the approved multicolor timeline. Segoe UI Variable/Segoe UI are read locally without font downloads. Layout is media | original timeline/player | rendered Shorts, left aligned, with actual episode title instead of promotional copy. Removed the oversized hero and unnecessary numbered headings; collapsed analysis/account details while keeping cancellation/retry visible. Installed and read the official Anthropic frontend-design skill inside the project at the user's request. No fake editor actions.

Actual browser checks: 1440px three-column studio and 380px responsive layout (page width 365px <= viewport 380px), source seeking, optional bounded preview, budget display, original playback continuing from 594s past 663s without boundary pauses. The forced cut-end pause is now opt-in via an unchecked source-limit checkbox. Tiny track pieces have no physical border minimum that would enlarge their click targets. Screenshots are saved under the job's qa directory. Confirmed source ranges were manually reviewed; automatic opening classification and editorial quality remain imperfect as documented.
