# Goal
Resolve all eleven reproducible findings in the 2026-10-13 audit, keep user media and preceding viewer-interest work, and activate the fixes in local Studio without KADR MCP.

# Current state
Two official tests fail after transport/shutdown updates. Finishing edits can reuse a stale episode draft or baked preview; queued renders read live caption files. Completed export selection trusts legacy metadata and fails on corrupt records. Phone post CSS, hash links, alpha masks and the 50-part submission limit disagree with supported flows.

# Constraints
All files/runtime/checks remain in F:\new_prodject. No new dependencies, paid model requests or global configuration changes. Preserve original plans, ASR, original MP4/SRT, uploads, and all pre-existing changes. Legacy exports remain readable by explicit ID, but unverified files must not be promoted into current playback. No KADR MCP calls.

# Implementation
1. Snapshot selected plan parts, styling and job captions under the existing manager lock at submission; render the snapshot and record caption revisions. Skip malformed/unverified finishing records with local diagnostics and original-file fallback. Align export requests to the existing 1–100 part domain.
2. Rebase clean episode appearance fields against current finishing state while preserving unsaved changes. Invalidate baked/pending previews after meaningful edits and use original source for previously finished videos.
3. Share browser card geometry between phone/finishing previews, remove stale post overrides, restore old hash-link navigation, and preserve avatar alpha.
4. Add regressions for the observed scenarios, update the two failing contracts, build/lint/smoke and run all Python tests. Document snapshot/legacy compatibility decisions.
5. Safely restart the verified idle Studio, inspect a real short render, and apply the user's stored style to the six-part draft if the source/profile still match. Preserve source hashes and verify rendered MP4s.

# Validation
Repository-native Node build/lint/DOM smokes; Python regressions with workspace TEMP/TMP and no pytest cache. Snapshot tests coordinate actual queued threads with events. Test old/corrupt records alongside valid completed exports. Test saved versus dirty UI drafts, stale preview rejection, hash routes, post CSS and 51-part application. Validate real render dimensions/audio/duration and unchanged base output hashes. Visual browser automation is policy-blocked; inspect local extracted frames instead.

# Risks and rollback
Snapshots consume memory proportional to selected plan/caption metadata, capped at 100 parts. Reconnecting old clients remains compatible; legacy exports keep their explicit links. Corrupt finishing metadata must not affect unrelated records. Revert new source behavior to roll back; do not delete preserved user state or media. Editorial montage quality and historical local inference speed are separate unaccepted limitations, not silently declared fixed by these technical checks.

# Progress
- [x] Confirm the audit scenarios and affected owners.
- [x] Fix backend snapshot/selection/contracts.
- [x] Fix frontend state/previews/layout/navigation and avatar alpha.
- [x] Add regressions, documentation and pass full checks.
- [x] Activate and verify real local outputs.

Full validation: 1456 Python tests and 654 subtests passed; frontend build/lint and both DOM smokes passed. The two previously failing contracts now pass. Activated current code in a verified idle Studio and rendered a real five-second source preview: H.264/AAC, 1080×1920, duration 5.000 s. Inspected extracted frame showing the saved Yumora/OH NO card, rounded media, avatar, footer and shadow. Baseline hashes preserve all six original MP4s and plan.json. Full six-part finishing export completed and verified; details below.

Completed real export `ex_88037cf632574b8ca9c7d1c54fcf0a38`: all six files are H.264/AAC 1080×1920 and match planned durations within 0.001 s. Current job playback uses these export URLs. All six MP4 HEAD and byte-range requests and all six SRT HEAD requests passed. Saving part 1 through the real save-videos endpoint produced a file with the new export's hash. Original six MP4 hashes and plan.json hash are unchanged. Evidence: `temp/audit-fix-verification/result.json` and `preview-frame.png`. Active Studio identity matches current source/build. No KADR MCP calls or model inference were used. Browser visual inspection remained unavailable through the blocked automation surface; DOM regressions and the actual rendered frame were verified.
