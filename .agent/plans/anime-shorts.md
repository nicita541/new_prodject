# Goal
Create a fully local Windows application that condenses a Russian dubbed anime episode into chronological numbered 1080x1920 videos, each at most 90 seconds, preserving original speech, story causality and speaker/action framing.

# Current state
The portable application, Russian UI, pinned runtimes/models and recoverable pipeline are implemented under F:\new_prodject. Test input is a 1433s Russian dubbed H.264/AAC episode (1920x1080, 30fps). Hardware: i5-12600KF, ~32GB RAM, RTX 5060 Ti 8GB. The first complete export produced 13 parts; technical checks and cached offline repeat passed, but visual/story quality was rejected. The requested broad audit is recorded in docs/quality-audit.md. A batch of confirmed fixes is integrated; a new complete export is required.

# Constraints
All project installations, caches, downloads, models, temporary and output files under F:\new_prodject. No global installation or system PATH edits. Runtime offline, loopback only. Original media unchanged. One job at a time. Russian original audio, no speed changes, no invented narration. Dynamic number of parts, 90s upper bound. Focus speaker/action, no blurred-background fallback.

# Implementation
1. Bootstrap portable Python, pinned packages, copied local FFmpeg distribution, portable llama.cpp and Qwen3.5-4B UD-Q4_K_XL/mmproj plus faster-whisper large-v3. Validate short GPU inference before full run.
2. Implement model analysis and persistent artifacts: probe, speech word timestamps, bounded ASR gap repair, shot boundaries, multimodal story events and crop anchors. ASR, 4B visual analysis, 9B story selection with thinking and 9B framing without thinking run sequentially. Both Qwen sizes/projectors are pinned locally.
3. Implement deterministic planner/renderer: validated source IDs, chronological non-overlapping intervals, word-safe splits, continuity context, subtitle remapping, smooth focus, atomic FFmpeg export.
4. Implement API/persistent job worker, import, cancellation/retry/resume, HTTP range serving. Build Russian local frontend and Windows start/setup scripts.
5. Run unit/integration/API tests and a real full episode, then cached offline repeat; inspect every rendered part and document remaining quality uncertainty candidly.

# Shared implementation contract
- Root config: app/config.py exports ROOT, DATA, JOBS, IMPORTS, TEMP, TOOLS, MODELS and setup_environment(). No module downloads automatically at runtime.
- Job artifacts: data/jobs/<uuid>/job.json and source.json; stage files probe.json, transcript.json, shots.json, events.json, plan.json; outputs in output/part_001.mp4 and matching srt; renders atomic.
- source.json: {path: absolute workspace-contained path, name: original basename}. Original file must stay untouched.
- job.json fields: id, source_name, status (queued/running/completed/failed/cancelled/interrupted), stage, progress (0..1), message, created_at, updated_at, error, outputs (relative output filenames), cancel_requested. API may add fields.
- Pipeline: app/pipeline.py run_job(job_dir: Path, report: Callable[[str,float,str],None], cancelled: Callable[[],bool]) -> list[str]. Raise InterruptedError on cancellation, descriptive exceptions on failure. Pipeline uses app.analysis.analyze(job_dir, source, report, cancelled) to return dict with probe, transcript, shots, events. Stage intermediates reused if validated.
- Analysis probe: {duration, width, height, fps, has_audio}; transcript: {language:'ru', words:[{start,end,text}], segments:[{start,end,text}]}; shots: [{id,start,end}].
- events: [{id,start,end,summary,kind:'story'|'opening'|'ending'|'recap'|'filler',importance:1..5,requires:[earlier event ids],focus:[{time,x,y,confidence}],boundary_times:[seconds]}]. Focus x,y are normalized source centers, absolute source time. Events are ordered contiguous windows from complete source; model may reference only provided source intervals. Non-story kind does not automatically remove high-importance narrative material.
- Plan selects story events and dependencies, consolidates overlapping intervals, retains original chronology. Public output plan shape owned by pipeline developer and consumed by UI only as JSON.
- Routes: GET /api/health; GET /api/sources (workspace MP4/MKV list + imported); POST /api/import multipart file -> {id,name}; POST /api/jobs JSON {source_id} -> job; GET /api/jobs -> list; GET /api/jobs/{id} -> job; POST /api/jobs/{id}/cancel; POST /api/jobs/{id}/retry; GET /api/jobs/{id}/plan; GET /api/jobs/{id}/files/{filename}. File names only output basenames, range supported. Frontend refresh via polling, no external CDNs.
- Source id is opaque server registry ID, never browser-provided absolute path. Jobs API adds `files`: [{name,url,subtitle_url,duration}] when completed. GET sources shape [{id,name,size}]. Health: {ready:boolean,missing:[str],busy:boolean}.
- A daemon app.worker subprocess --job <uuid> invokes run_job. Parent app server owns persistence/single-job lock and cancellation. API/worker developer owns app/jobs.py, app/server.py, app/worker.py and API tests. Root owns config/analysis/model subcommands/setup/tests for analysis. Pipeline developer owns pipeline/planner/media/subtitle files and tests. UI developer owns app/static and user README only.

# Validation
Unit tests for timeline validation/dependency closure/90s splits/word boundaries/subtitle clocks/crop clamps/malformed model output. API tests for path traversal, MIME/import validation, single job, cancel/retry/range and long Russian paths. Real short GPU inference followed by full source processing, offline repeat and thumbnails of every output. Record actual durations/timing/quality findings.

# Risks and rollback
Small local VLM may miss narrative or speaker identity. Expose saved events/plan and surface uncertainty; do not claim quality solely from export success. Sequential inference limits VRAM. Keep source untouched, outputs per UUID, preserve diagnostic artifacts. Portable setup is reversible by removing explicitly selected generated project folders; no automated recursive deletion in setup.

# Progress
- [x] Inspect source and hardware; agree scope/preferences.
- [x] Bootstrap and short GPU checks.
- [x] Model analysis and persisted stages.
- [x] Planner/renderer and tests.
- [x] API/UI and tests.
- [ ] Full episode and offline repeat, visual/story QA.

# Observed validation and adjustments
- Portable Python 3.12.14, FFmpeg 8.0.1, llama.cpp b11316 Vulkan; models and large archives checked against pinned SHA-256. Package versions frozen in requirements.lock.txt.
- Real 35-second GPU smoke completed ASR and portrait MP4/SRT export. Full-episode ASR: CUDA int8_float16, 1300 words, 103.45 seconds. Model processes release GPU memory before the next stage.
- 119 tests and 9 subtests passed in 16.40s, including real Windows child/grandchild cancellation with an unrelated process surviving, real 90-second encoding, fractional-cut audio clocks, UTF-8 paths, corrupt-input rejection, simulated OOM CPU retry, ASR repair, question/answer context protection and stale storyboard-pixel regression checks.
- Initial quality review rejected a keep-almost-everything montage and center-only crops. Added independent credit classification, source-unit condensation, silent shot boundaries, explicit warning display and temporal focus inference. Quality validation remains pending until the final outputs are inspected; technical success is not acceptance.
- Offline verifier blocks external Python connections and reports checkpoint reuse explicitly; it does not change system networking. Final measurements will be saved with the job.
- Actual ASR gap repair accepted 6 of 9 candidates. It restored a missing word and moved the negation from a false timestamp roughly 11 seconds early to the spoken sentence; an inflection-mismatching question repair was rejected and its context remains protected.
- Full-source review exposed mixed-window credit errors: an exclusion selected the silent office instead of the opening, and closing musical scenes were treated as new story. Per-unit confirmation now preserves the office; a comparison with earlier retained story correctly classified a closing musical restatement in a real 9B CPU diagnostic. General closing-context refinement is being integrated. The 13-part first full plan is rendering; it has not passed quality acceptance.
- Timestamp-matched original/export comparisons exposed confidently incorrect 4B coordinates in shared shots: a face is partly outside the crop around 42s and a cashier is clipped around 352s. These are actual quality failures being investigated, not accepted framing.
- Analysis v6 keys extracted frames by source identity plus actual timestamp. Derived event signatures include story/framing versions. A story-events checkpoint separates validated story decisions from later framing retries.
- Broad audit completed; details in docs/quality-audit.md. Confirmed fixes cover part-boundary replica splits, pixel-width subtitle overflow, missed shot transitions and moving action focus, title/closing restatements, render crop boundaries, failure cleanup, import limits and UI action races. The independent full local rerun is job 17009d33-5efd-4dfb-8907-a44f5b69d9dd. Only source/probe/audio/repaired ASR facts were copied after verifying the original SHA; no model decisions or exported videos were copied.
- Optional DeepSeek implementation and three real samples are documented in .agent/plans/deepseek-budget.md. The full review initially used local analysis. The user subsequently requested selective cloud review of local uncertainty; implementation and checks are in .agent/plans/hybrid-analysis.md. Full-series quality acceptance remains pending.
- The user rejected the coordinator-imposed USD 0.01 API ceiling; it is removed. API balance preflight, usage ledger, cache and no paid auto-retry remain. Server reload exercised real checkpoint recovery during full local model analysis: after explicit cancellation, restart resumed at the first unfinished story scene, with all 36 visual checkpoints reused. Before/after observer records are preserved separately.
