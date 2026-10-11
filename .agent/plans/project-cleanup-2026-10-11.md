# Project cleanup

## Goal
Remove obsolete code copies, unused source and accumulated disposable test files while preserving the working studio and the user's latest DeepSeek run.

## Current state
The checkout is `codex/dramatic-montage`. Latest verification is `20261011_112517_ab2f6eae`: 1235 Python tests and frontend/technical checks passed; real-model acceptance timed out. `temp` contains many generated UUID test directories. `scratch` contains old implementation copies and one-off patch scripts. `app/provider_balance.py` has no runtime callers and refers to removed accounting helpers. Vite scaffold assets/styles have no consumers. Some calibration tests still depend on a useful helper in scratch.

## Constraints
All operations remain inside F:/new_prodject. Preserve data, media, settings, models, tools, dependencies, paid DeepSeek cache, raw-video calibration/evidence, latest verification and related logs. Preserve the user's untracked log-collection script. Do not start paid analysis or publish reports. Retain supported legacy UI/routes and API compatibility. Stay in this checkout because the task includes cleaning its local artifacts.

## Implementation
1. Audit references and classify generated artifacts; save a private deletion inventory under temp/project-cleanup-20261011.
2. Move the used calibration helper into scripts, update its current-module loader/tests and remove the stale scratch fallback. Remove the retired balance module and unused frontend scaffold files.
3. Delete only inventoried disposable test directories, old scratch experiments and regenerable bytecode caches, with resolved-path/link validation. Preserve useful source calibration/evidence and report history.
4. Run the existing Python suite, React tests/lint/build and studio script checks. Record actual cleanup totals and any failures.

## Validation
Portable tools/python/python.exe -m pytest -q tests; frontend npm test, npm run lint, npm run build; node checks and existing studio smoke scripts. Validate preserved report/catalog/settings hashes and remaining calibration tests. git diff --check.

## Risks and rollback
Tracked source changes can be restored from Git. Disposable test artifacts and scratch code copies are deleted permanently; reusable source calibration/evidence, reports, application data and paid responses remain. Stop deletion on changed candidates, reparse points, protected roots or unexpected errors; save a receipt of partial progress. No broad data cleanup or dependency removal.

## Progress
- [x] Identified live entry points, validation commands and latest test outcome.
- [x] Freeze deletion inventory and verify protected files.
- [x] Remove obsolete source and scratch copies; promote the retained calibration helper to scripts and exercise live modules in tests.
- [x] Clean generated artifacts and record reclaimed space: 210,637 files / 2,687,487,252 bytes (2.503 GiB) across the initial and post-validation receipts. Also remove the empty restricted pytest cache and empty source directories. No disposable UUID test directories remain.
- [x] Verify application and frontend checks: 1235 Python tests / 596 subtests, 133 React tests, frontend build, both Studio smoke scripts, syntax compilation of 180 Python source files and git diff --check passed. Lint passed with 35 pre-existing warnings and zero errors. Sandbox-only process/access failures were resolved by rerunning the checks outside sandbox with workspace-local temporary paths.

## Results
Private inventory, deletion receipts, protected-file hashes and check logs are under `temp/project-cleanup-20261011`; `summary.json` contains the combined totals. Protected catalog/settings/last-DeepSeek-report/log-collector hashes remained identical before cleanup, after cleanup and after tests. App data, imported media, outputs, models, tools, dependencies, response caches and raw calibration/evidence were outside deletion scope. The user's latest DeepSeek run remains preserved with its real-model TIMEOUT; no new paid/model run was performed.

Removed the retired balance implementation (its existing disabled API endpoints remain), Vite scaffold CSS/assets, 56 obsolete experimental source/patch files, 11 one-off temporary scripts, two old diagnostic ZIP copies and regenerable bytecode/test caches. Removed tests' fallback to old scratch source and moved the still-used calibration tool into tracked scripts. Documentation now describes the actual retired-accounting behavior and portable frontend commands. Cleanup is included in the final audit/manual-provider commit on the existing development branch; the pre-existing untracked log collector is untouched.
