# Goal
Make montage settings compact: import-only source, appearance choices with a separate card editor, small analysis/music controls, and processing choices beside the launch button. A plan rebuild must never silently start a full run.

# Current state
Studio source has processing modes but the served dist and running backend predate them. Recent jobs omit processing_mode and reuse_job_id. The current pipeline already implements strict plan_only without inference or encoding. Editor settings expand every optional control inline.

# Constraints
Preserve existing changes and jobs. All artifacts/runtimes stay under F:/new_prodject. No inference or real montage runs for verification. Keep API defaults compatible.

# Implementation
1. Replace large editor sections with compact rows, appearance choices and focused dialogs; move mode selection into a split launch button.
2. Advertise processing modes in health and reject unsupported selective launches before mutation, preventing an old backend from ignoring the requested mode.
3. Add UI launch-payload and stale-backend regressions; run existing backend mode tests and Studio checks/build.
4. Update frontend documentation and refresh the idle local service through its verified shutdown flow.

# Validation
tools/node/node.exe frontend/scripts/check-studio.mjs --lint; check-studio.mjs; build-studio.mjs. tools/python/python.exe -m pytest -q tests/test_processing_modes.py tests/test_api.py. Inspect served assets and health; inspect UI where available.

# Risks and rollback
Dialogs must preserve drafts and keyboard access. Runtime refresh is idle-only with workspace identity checks. Revert task edits and rebuild dist to restore the previous layout; no media or job deletion.

# Progress
- [x] Identify layout and stale runtime cause
- [x] Compact editor and strict launch contract
- [x] Regression checks and build
- [x] Documentation and idle runtime refresh

Validation: backend processing/API suite passed (53 tests, 4 subtests). Studio syntax, bridge smoke and DOM smoke passed; DOM smoke verifies stale-backend rejection before writes and the actual plan_only launch payload. Production dist rebuilt. Browser inspection confirmed import-only settings, three appearance choices on one row, a separate card dialog with focus restoration and the split-button mode menu. Screenshot saved under scratch/compact-montage-settings.png. The old idle workspace server was stopped with its fetched identity through /api/studio/shutdown; the updated server reports all modes and studio_status() returns current. No real inference, new job or media export was started.
