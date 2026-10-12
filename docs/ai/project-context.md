# Project context

Store only durable, non-obvious facts that help future engineering work.

## Build and run
<!-- Non-obvious toolchain/platform/build facts. Prefer actual config files as the source of truth. -->

## Conventions
<!-- Project-specific conventions that are not already obvious from code or formatter/linter config. -->

## Environment constraints
<!-- Supported platforms, versions, deployment constraints, generated-file rules, etc. -->
- User requires all project installs, downloads, caches, temporary files and outputs inside `F:\new_prodject`; no global installs or other drives. Use the portable interpreter `tools/python/python.exe`.
- Windows 11, RTX 5060 Ti (8GB), i5-12600KF, ~32GB RAM. ASR uses local CTranslate2 CUDA libraries; VLM uses portable llama.cpp Vulkan. Models execute sequentially in owned child processes to release VRAM.
- Python 3.12 `tempfile.TemporaryDirectory` creates restrictive Windows ACLs in this sandbox; tests use ordinary UUID directories with inherited ACLs under project `temp`. Pytest cache provider disabled to avoid that same creation issue.

## Operational notes
<!-- Stable details that repeatedly matter during development or release. -->
- `start.bat` starts a loopback-only server at `http://127.0.0.1:8765`. Explicit `setup.bat` downloads dependencies/models; runtime never downloads automatically. Keep the server attached to the interactive Windows desktop because native folder selection for video export needs a visible dialog.
- Qwen 4B initial visual artifacts live in `models/qwen`; Qwen 9B story and final framing artifacts in `models/qwen9`. Both projectors use the filename `mmproj-F16.gguf` but have different contents and checksums. Never identify a projector solely by basename. Story uses thinking; framing disables it. Both run sequentially.
- Run checks with `tools/python/python.exe -m pytest -q`. Package pins are in `requirements.lock.txt`; downloaded wheels remain in `cache/wheels`.
- Analysis modes are persisted per job. Studio offers local, `deepseek_plan` and temporary `antigravity_manual`; older jobs may use `hybrid` or `deepseek`. Manual replaces9B queries with export/import packets, while local4B/ASR remain native. KADR never invokes agy; the user-run scenario uses the existing authorized official CLI. See docs/antigravity-manual.md. In `deepseek_plan`, the remote model handles story/analysis while final framing, audio, and rendering stay local. Settings and API keys remain under ignored `data/settings`.

Do not use this file as a chat log or changelog.

- Antigravity file automation is opt-in per stopped job. The user separately starts `scripts/run_antigravity_job.ps1`; KADR never launches agy. ManualVision validates atomically published results and continues in the same worker. The script's budget is separate from whole-pipeline runtime; Google consumer-plan compatibility of this complete workflow is not certified. UI progress uses `stage_progress` exclusively, with unknown fractions shown as activity rather than a fabricated percentage.

- User-facing one-click entry is `1_Запустить_Кадр.bat` → `start.bat` → `app.launcher`. It starts a missing server, opens the page after readiness, and reuses an existing server. The UI explicitly defaults to DeepSeek-plan/cinema/accent; missing settings and legacy API callers preserve local/portrait/classic.
- The main UI is Studio Edition (`frontend/public` → Vite `frontend/dist` → FastAPI); React and `/legacy` are secondary. `остановить_Кадр.bat` stops only the verified idle server and preserves data. Runtime identity includes all Python app modules and all four Studio assets. Start/setup/verification prefer workspace portable Node/npm and set temporary/npm cache paths under the workspace.
- `finishing/` at workspace root contains persistent subtitle/profile/export state in addition to `data/`; include it in backups. The hierarchical component/storage map is in `docs/audit/README.md`.
- Genuine short local measurements use `scripts/benchmark_local_pipeline.py`; clips, independent jobs and raw metrics remain under the chosen `temp/` directory. Fresh/resume phases stay separate; the wrapper prohibits DeepSeek HTTP calls. Resource samples measure the whole computer, not just the worker.
- Performance is an ongoing priority: when an analysis stage is slow, inspect request fanout, frame preparation, cache reuse and actual model timings immediately, and test concrete improvements. Preserve semantic checks and the authorized run; prepare isolated optimizations rather than silently stopping a job. The target for a genuine three-minute test is about 30 minutes.
- Launch is not gated by an account balance, monetary spending ceiling, or uncertain-charge ledger. Compatibility balance endpoints return disabled metadata; historical monetary files are not read or changed. A DeepSeek request makes one initial attempt and up to two retries; cancellation, HTTP 401/403, and TLS certificate verification failures stop immediately. Timeline source playback and cached re-export are local and do not send paid requests.
- Keep `main` as the user's stable working checkout. Future development should start from `main` in an isolated `codex/*` branch/worktree so app data and the interactive Windows folder picker remain available from the stable checkout. Before cleaning `data/`, preserve imported sources, settings, and each active episode's latest completed job and source-analysis lineage; completed job folders are also the on-disk job catalog.
- `data/library.json` is the additive anime/episode catalog; legacy jobs group by registered source identity, new jobs persist episode_id before launch. One source per active episode. Delete controls use recoverable catalog tombstones; they never remove physical media or ledger records. Restore checks identity/source conflicts.
