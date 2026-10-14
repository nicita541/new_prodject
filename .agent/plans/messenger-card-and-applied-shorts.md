# Goal
Applying finishing settings updates the Shorts that Studio plays/downloads, and a messenger-style card supports choosing a preset or uploading a channel avatar. Preserve original media and montage decisions.

# Current state at task start
The editor Save action persists settings/captions but does not render. Export creates isolated MP4s, while review and save-to-folder still use base job outputs. Cards have a flat rectangle, initial-only avatar and different compact/post geometry.

# Constraints
Keep prior viewer-interest edits intact. All assets, validation and exports remain under this workspace. Render locally from existing cuts/ASR, without model requests. Use bounded, decoded image uploads, owned episode asset paths and immutable export IDs. Preserve original plan and outputs; expose the latest completed finishing render per part.

# Implementation
1. Add an owned avatar asset format and profile fields, bounded upload/read APIs and renderer resolution. Preserve old profiles.
2. Redesign raster and browser cards together: dark messenger bubble, layered soft shadow, rounded media, avatar and channel identity. Palette: #101c27 background, #1b3042 bubble, #29465d border, #79bce8 identity, #edf5fc text. Existing Segoe UI fonts, left alignment, no invented dates/read counts.
3. Make Apply save and render the montage, show progress and publish successful files to review/downloads. Keep earlier outputs on failure/reload; support single-part export.
4. Verify backend source preservation, avatar validation, UI apply/export/reload, raster layout and a real short render. Deploy to idle local Studio and apply the user's saved Yumora/OH NO settings to the existing six-part draft.

# Validation
Workspace Python tests for finishing/social frames/server bounds and frontend native build/lint/smokes. Inspect real card PNG and live browser. Verify registered rendered files with actual FFprobe/media responses. Never call test fixtures real exports.

# Risks and rollback
Image payloads and model/profile text are untrusted; decode only PNG/JPEG/WebP, limit pixels/bytes and store canonical PNG with UUID filenames. Export failure must not promote partial files. Latest files are presentation pointers, not replacements of original job data. Revert source/pointers to restore original review behavior; preserve original videos and uploaded assets.

# Progress
- [x] Trace saved settings versus displayed video.
- [x] Implement avatar, messenger layout and completed-export selection.
- [x] Verify backend and UI behavior.
- [x] Apply current saved style and inspect real output.

## Runtime recovery and connection verification (2026-10-13)
The previous idle Studio process had accepted shutdown but retained the instance lock after closing its listener. Verified its workspace executable, exact command, creation time, and idle shutdown log before stopping that process. Added a five-second Uvicorn graceful timeout and launcher checks for lock release. A real paused source download now permits shutdown and lock release in 5.279 seconds. Current Studio is running with the on-disk identity.

Opening projects previously spent 6.111 seconds in `/api/jobs`, mainly counting historical scene-feature maps. Added an opt-in summary response and selected-job detailed progress for the processing screen; the first fresh-server summary request measured 0.476 seconds. Existing full API/MCP responses remain available. Focused backend checks: 120 tests and 15 subtests passed; native frontend build, lint, bridge and exact DOM smokes passed.

Both MCP connections answer reads and the product MCP sees the correct projects. Its running process retains its pre-edit backend fingerprint (`backend_matches=false`); reconnect both MCP sessions before product writes, as documented in `docs/mcp.md`. The tool set has no desktop MCP restart action. Browser automation rejected the existing loopback tab through its URL policy; no alternative browser surface was attempted. At that stage real finishing export and live visual acceptance were pending. Subsequent completion is recorded below; the original MP4s remain preserved.

## Completion after audit fixes
The user authorized continuing without KADR MCP. Fixed the eleven audit findings and passed 1456 Python tests plus 654 subtests, native frontend build/lint/smokes. Safely activated current Studio and completed the six-part export `ex_88037cf632574b8ca9c7d1c54fcf0a38` with the user's saved Yumora/OH NO profile. Verified actual rendered frame, H.264/AAC 1080×1920, all planned durations, real playback/download endpoints and save-to-folder. The original six MP4s and plan retain their baseline SHA-256 hashes. Review/downloads now select the new verified exports; originals remain preserved. Browser automation remains unavailable; UI behavior was checked through DOM integration tests rather than a claimed live browser pass. Editorial drive and fresh model-analysis performance remain separate acceptance work.
