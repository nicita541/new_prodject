# ExecPlan: DeepSeek Cache Sharding & Rotation

## Goal
Resolve technical debt item #2 from `project-map.md`: "Огромная директория `cache/deepseek/` — тысячи JSON-файлов с хешами в одной плоской папке (медленный readdir, нет ротации/очистки)".
Implement 2-character hex prefix sharding (`cache/deepseek/ab/abcdef...json`), transparent fallback to legacy flat files for 100% backward compatibility, lazy/batch migration of existing files, and an automated/on-demand rotation and pruning mechanism (`prune_cache`).

## Current state
`cache/deepseek/` contains over 2,000 JSON response files in a single flat directory.
All reads and writes currently assume `RESPONSES / (identity + '.json')`.
This causes:
1. Sluggish directory traversal and file lookups on NTFS / Windows filesystem.
2. Unbounded growth of cached files with no pruning, rotation, or corrupt entry removal.
3. No utility to inspect cache stats or clean up orphaned temporary files.

## Constraints
1. **100% Backward Compatibility:** Legacy flat cache entries must remain discoverable and readable without losing previously paid and cached responses.
2. **Zero Breaking Changes:** External callers, tests in `tests/test_deepseek.py`, and public API contracts must continue functioning without modification.
3. **Safe Storage:** All writes must use `atomic_json` with fsync and directory bounds checking (`relative_to(ROOT)`).
4. **Execution Rules:** Work strictly within `F:\new_prodject`. All tests must pass.

## Implementation Milestones

### Milestone 1: Sharded Cache Access & Lookup in `app/deepseek.py`
- Add `cache_path(identity, responses_dir=RESPONSES)` that checks sharded location `dir / identity[:2] / (identity + '.json')` first, falling back to flat `dir / (identity + '.json')`.
- Update `_query` to use `cache_path` for reading and write new cache files to the sharded path `RESPONSES / digest[:2] / (digest + '.json')`.

### Milestone 2: Cache Rotation, Pruning, and Migration Utilities
- Add `migrate_flat_cache(responses_dir=RESPONSES)` to safely move legacy flat files into 2-char sharded subfolders.
- Add `prune_cache(responses_dir=RESPONSES, max_entries=..., max_bytes=..., max_age_days=..., remove_corrupted=True)` to remove corrupted/empty JSON files, prune LRU entries beyond limits, and clean up leftover `.tmp` files.
- Add `cache_stats(responses_dir=RESPONSES)` for diagnostic insight.
- Create CLI maintenance script `scripts/prune_cache.py`.

### Milestone 3: Testing & Verification
- Add comprehensive unit tests in `tests/test_deepseek.py` for:
  - Sharded write and read.
  - Transparent fallback read from legacy flat files.
  - `migrate_flat_cache` moving flat files to sharded subdirectories.
  - `prune_cache` removing corrupt files and respecting size/entry limits.
- Run `tests/test_deepseek.py` and the full regression suite (`tests/`).
- Migrate existing flat cache files in `cache/deepseek/` using the verified migration tool.

## Validation
- `tests/test_deepseek.py` passes all existing and new tests.
- Full test suite passes 100%.
- `cache/deepseek/` directory is cleanly partitioned into 2-char subdirectories, with no flat file clutter.

## Risks and rollback
- **Risk:** Missing cached responses causing unnecessary paid DeepSeek API re-fetches.
  - *Mitigation:* `cache_path` checks both sharded and flat paths before reporting a cache miss.
- **Rollback:** `git checkout app/deepseek.py` and run inverse flat flattening if needed.

## Progress
- [x] Milestone 1: Sharded cache access in `app/deepseek.py`
- [x] Milestone 2: Pruning, rotation, and migration utilities (`target_cache_path`, `cache_file_path`, `migrate_flat_cache`, `prune_cache`, `cache_stats`, `scripts/prune_cache.py`)
- [x] Milestone 3: Unit tests and full regression verification (all 18 tests in `test_deepseek.py` and 421/421 repository tests passed)
- [x] Cache migration run on existing `cache/deepseek`: 2,005 flat files migrated into 256 2-char shards with 0 flat files remaining.
