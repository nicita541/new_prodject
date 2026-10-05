# ExecPlan: Worktree Cleanup & Headless Save Destination

## Goal
Resolve technical debt items #5 and #9 from `project-map.md`:
1. **Item 5 (Worktree Cleanup):** Remove redundant/duplicate codebase checkouts in `.kilo/worktrees/` (`bottled-motorist`, `teal-strand`) and eliminate stale references, freeing disk space and removing desynchronization risk.
2. **Item 9 (Headless Save-Videos Destination):** Add headless/CI direct destination path support to `SaveVideos` model and `POST /api/jobs/{id}/save-videos` endpoint, bypassing interactive `tkinter` modal dialog while maintaining full backwards compatibility and adding `AUTOSHORT_DOWNLOAD_DIR` environment variable fallback.

## Implementation Milestones
- **Milestone 1: Worktree Cleanup**: Inspect and remove duplicate working trees in `.kilo/worktrees/` (`bottled-motorist`, `teal-strand`).
- **Milestone 2: Server API Extension**: Add `destination: str | None = None` to `SaveVideos` in `app/server.py`. In `save_videos()`, resolve and validate `destination` directly when provided, bypassing `download_picker_lock` and `tkinter`. In `choose_download_directory()`, add `AUTOSHORT_DOWNLOAD_DIR` environment variable fallback.
- **Milestone 3: Test Coverage**: Add unit tests in `tests/test_api.py` covering direct destination saving, invalid destination paths, empty destination, self-output path rejection, and `AUTOSHORT_DOWNLOAD_DIR` fallback.
- **Milestone 4: Verification**: Verify all 35 tests in `test_api.py` and all 428 repository tests pass.

## Progress
- [x] Milestone 1: Duplicate checkouts in `.kilo/worktrees/` removed.
- [x] Milestone 2: `SaveVideos.destination` direct path and `AUTOSHORT_DOWNLOAD_DIR` env fallback implemented.
- [x] Milestone 3: Unit tests added in `tests/test_api.py`.
- [x] Milestone 4: Full verification complete (428/428 tests passed).
