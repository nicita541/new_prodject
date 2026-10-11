# Full application audit and local performance measurements

## Goal
Give the user a reliable, multilevel map of KADR: entry points, UI/API/worker ownership, every processing block, local models, persistent and temporary files, caching, failure/cancellation paths and practical improvement points. Verify everyday operation and measure real all-local 120-second and 180-second source runs with tables and charts. Fix confirmed operational bugs within this scope.

## Current state
Workspace is F:/new_prodject on codex/dramatic-montage, with the completed cleanup changes still uncommitted. FastAPI serves Studio Edition and supports React/legacy routes. Portable Python, Node, FFmpeg, llama.cpp and models are installed under the workspace. Latest DeepSeek acceptance timed out; that is preserved evidence, not local performance evidence. After cleanup, 1235 Python and 133 React tests, build and Studio smoke checks passed.

## Constraints
Preserve existing user edits, source videos, application catalog/history, outputs, credentials and paid response cache. All audit artifacts, tools, caches and runs stay inside this workspace. No DeepSeek calls, uploads, publishing or global installation. Run GPU/model benchmarks serially and distinguish fresh computation from cached resume. Do not weaken quality gates to get a green result. Record failures and timeouts honestly. Ask about choices that materially change product behavior; continue independent inspection meanwhile.

## Implementation
1. Map the repository and production routes. Delegate independent architecture documentation, operational entry-point review and performance/instrumentation review with disjoint ownership.
2. Build a hierarchical architecture guide with diagrams, module and artifact maps, settings/provider contracts and source-to-export paths. Include source evidence and explain uncertainty.
3. Exercise launch/readiness/relaunch/stop, UI actions and log/test BAT behavior. Repair demonstrated defects with focused regression protection.
4. Select a preserved real input, prepare isolated 120s and 180s clips, establish exact local provider/runtime/cache conditions and run the existing production harness. Collect wall time, stage/model/request/token/cache/render/resource measurements. Preserve failed checkpoints and inspect the first causal failure rather than claiming acceptance.
5. Produce readable comparison tables and standalone charts, separate nested timings and model startup/request time, and calculate processing time per minute of input. Validate resume separately where practical.
6. Integrate findings into a prioritized audit index, verify changed code and complete appropriate Python/frontend/interface checks. Update durable project context only where evidence changes it.

## Validation
Use existing test commands and scripts: portable Python pytest, frontend npm test/lint/build, Studio smoke scripts, offline/full-pipeline harnesses and local API/UI checks. Real local benchmark manifests must identify source length, provider/models, fresh/cache state, stages, exit status and output checks. Verify no remote provider calls, no outside-workspace paths and no exposed secrets. Report reproducible commands and limitations.

## Risks and rollback
Local model runs may be slow or fail quality checks. Bound and observe them, retain diagnostic artifacts and report measured partial work instead of bypassing checks. Keep active user work isolated from benchmark job directories and owned processes. Changes are small and reversible through Git; do not delete retained original evidence. No production data migration or release is planned.

## Progress
- [x] Create plan and begin work immediately.
- [x] Architecture and storage map: active UI, provider paths, 66 app modules, scripts/tests/frontend registry, persistent/temporary storage and four detailed diagrams.
- [x] Launch/stop/UI/log/BAT audit and fixes; real source/output playback, cancellation/retry on isolated Windows worker and idle shutdown verified.
- [x] Real120s local attempt measured; timeout at3600s, no montage.
- [x] Real180s local attempt measured; timeout at3600s, no montage.
- [x] Timings, metrics, five SVG charts and improvement priorities exported from immutable phase snapshots.
- [x] Integrated verification and final audit index; technical full suite1286 Python/133 React passed. Separate final manual-provider focused checks108/8 subtests and report/entrypoint tests8 passed.

## Evidence and decisions

- The 120s/180s excerpts are prepared from seconds 300–420 / 300–480 of the preserved real episode, with genuine automatic ASR and fresh independent local jobs. Raw evidence is under `temp/local-audit-20261011`; remote HTTP calls are forbidden by the wrapper. Models/analysis code remain unchanged during measurements.
- 120s: audio preparation0.205s, ASR process28.517s (CUDA), two4B startups about4s each. Both120/180s attempts finished with timeout before planning/render; complete-run speed remains unknown beyond the measured lower bound.
- UI played real source/Shorts and paused both; browser warning/error list was empty in that check. UI demo/log/accounting/copy labels and media state callbacks were corrected, and Vite build passed.
- Real BAT startup reproduced closed JSON log handlers caused by Uvicorn reconfiguration. Handler restoration fixed it; repeated real startup reused the same PID and idle stop exited normally.
- Exact-identity idle shutdown API was exercised against owned servers and completed normal Uvicorn shutdown. Busy/identity/race guards have focused tests.
- User explicitly chose to retain the eyecatch heuristic and record its risk. No behavioral eyecatch change will be made in this audit.
- Audit index and prioritized findings are in docs/audit/README.md/findings.md; final first-attempt reports distinguish timeout from completed montage. The user subsequently set a30min target for180s, so future benchmark/default full-AI verification caps are1800s. The measured local performance does not meet that target.
- The later requested manual Antigravity feature is documented separately in manual-antigravity-exchange.md and docs/antigravity-manual.md. Its cloud requests do not enter the all-local benchmark tables.
