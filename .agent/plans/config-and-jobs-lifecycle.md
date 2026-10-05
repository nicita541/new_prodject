# ExecPlan: Config & Jobs Lifecycle Optimization

## Goal
Resolve technical debt items #6, #7, and #8 from `project-map.md`:
1. **Item 6:** Remove module-level side-effect execution of `setup_environment()` in `app/config.py` (L65), make it idempotent, and eliminate unintended filesystem/environment mutations during module imports.
2. **Item 7:** Fix `sources.json` write-on-every-list and race conditions: reload on-disk state safely in `list_sources()` and `register_import()`, and only persist when sources actually change.
3. **Item 8:** Add `delete_job` and `prune_jobs` rotation capabilities to `JobManager` and expose them via API (`DELETE /api/jobs/{id}`, `POST /api/jobs/prune`) to prevent unbounded accumulation of job directories in `data/jobs/`.

## Current state
1. `app/config.py` executes `setup_environment()` at import time (line 65), mutating `os.environ` and creating folders before any application logic runs.
2. `app/jobs.py`'s `list_sources()` writes `atomic_json(self.data / "sources.json", self.sources)` unconditionally on every call, even when nothing has changed. Manual edits to `sources.json` can be overwritten by stale in-memory state.
3. `data/jobs/` accumulates directories indefinitely without rotation, deletion, or automated pruning.

## Constraints
1. **100% Backward Compatibility:** All existing tests, endpoints, and job lifecycle invariants (e.g. Windows Job Object, atomic JSON with fsync, busy mutex) must remain intact.
2. **Zero Breaking Changes:** Calling `setup_environment()` explicitly must continue configuring the environment as before.
3. **Safe File Operations:** Job deletion and pruning must never delete the currently active running job.

## Implementation Milestones
- **Milestone 1: Clean `app/config.py`**: Remove import-time execution of `setup_environment()` and make it idempotent.
- **Milestone 2: Optimize `sources.json` in `app/jobs.py`**: Reload on-disk state and only write when sources change.
- **Milestone 3: Job Deletion & Pruning in `app/jobs.py` & `app/server.py`**: Implement `delete_job` and `prune_jobs` with full tests.
- **Milestone 4: Verification**: Run `tests/test_jobs.py`, `tests/test_api.py`, and the full regression suite.

## Progress
- [x] Milestone 1: Clean `app/config.py` (import-time side-effect removed, setup_environment is idempotent)
- [x] Milestone 2: Optimize `sources.json` (disk state merged, writes only on actual changes)
- [x] Milestone 3: Job Deletion & Pruning (`delete_job`, `prune_jobs`, and API endpoints `DELETE /api/jobs/{id}`, `POST /api/jobs/prune`)
- [x] Milestone 4: Full verification (all 19 tests in `test_jobs.py`, 33 in `test_api.py`, and 426/426 in full suite passed)
