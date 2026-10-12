# Goal
User starts official agy direct script once separately. KADR consumes validated files and continues the same pipeline without packet-by-packet import/retry. Exercise authorized project д episode 1, preserving checkpoints.

# Current state
ManualVision exports deterministic per-query packets and raises AnalysisPending. A standalone PowerShell script handles one packet. Job 00a9e488-dbe1-4614-9ec1-cf443e26083e was cancelled at ASR; prepared 1420.173055-second source remains.

# Constraints
No CLI subprocess/auth access inside KADR, API keys, proxies or account rotation. Existing providers/semantic validation and source algorithms remain. Default manual mode remains compatible. Files stay F; installed official agy profile on C is user-authorized. Google FAQ explicitly supports direct scripting but does not explicitly approve this complete file exchange workflow; separate installation alone is not an exemption.

# Implementation
1. Opt-in job-local file reception: same worker waits for current query, validates bounded atomic result, preserves native cancellation and caches. Deadline/error pauses rather than degrading analysis.
2. Separate user-started job script observes only current packet, processes sequentially, locks against duplicate runners, publishes atomically, stops on cancel/errors/deadline. No KADR HTTP control.
3. Existing manual panel exposes toggle, script command, runner status. Document boundary/rollback.
4. Verify transport, cancellation/resume, UI build and actual selected job within bounded runtime.

# Validation
Existing pytest transport/API/jobs tests plus focused wait/import/cancel/timeout tests. PowerShell parser and genuine CLI run. Frontend build. Real job status, stage timings, packets and final output inspection; incomplete run is not success.

# Risks and rollback
Cloud quotas/invalid model output pause with retained packets; do not blindly retry paid requests. Consumer-plan wrapper limitation cannot be certified away by placing script outside app. Turn off auto-import at idle and return to Qwen. No native algorithm changes.

# Progress
- [x] Inspect official FAQ and target job.
- [x] Implement file automation and separate script.
- [x] Correct Studio to show stage-specific counters/checkmarks; add streaming ASR progress bound to current run.
- [x] Focused checks: 91 tests / 8 subtests, additional progress/provider checks 70 tests / 28 subtests, frontend builds passed.
- [x] Genuine original KADR packet through separate job script: CLI 16.649s, 32526 total tokens, automatic import and warm cache passed. Receive elapsed 50.203s includes initial script startup and corrected PowerShell null-marshalling failure; not model latency.
- [x] Full regression found four stale 2200-second expectations (implementation intentionally 1800) and Windows concurrent finishing-status access. Fixed expectations and serialized status read/write; affected suite 111 tests / 33 subtests passed. React 133 tests, lint (existing warnings), build passed.
- [x] Full Python retest: 1295 tests and 609 subtests passed in 150.91s, one dependency deprecation warning. Real Studio shows stage counter 968/1800, 54%, preparation/ASR checkmarks and independent runner waiting; refreshed UI uses current assets.
- [ ] Authorized full job resumed after mistaken interpretation of deferring parallelization. Full-series result remains pending. User explicitly approved separate script limit 180 minutes; 30-minute target for 3-minute tests unchanged.
- [ ] Verify and document.
- [ ] Exercise selected job, report actual outcome and commit.

## User-requested pause, 2026-10-12

Stopped only on the user's explicit request to continue tomorrow. Same full job 00a9e488-dbe1-4614-9ec1-cf443e26083e is cancelled at analyze: 87/129 semantic scenes complete, 325 durable chunk checkpoints, preparation/ASR/scenes complete, no full-job Gemini packets yet. Native cancel API terminated the worker tree; independent agy runner exited normally with status stopped, wall5440.584s; read-only observer stopped. Keep Studio available, do not restart the job overnight.

Uncommitted performance work is tracked in local-analysis-throughput.md. Python production modules remain unchanged so resume can reuse existing semantic identities. Frame batching is still an isolated tested candidate; do not integrate until the resumed full job finishes. Official single-main-agent CLI persona has one genuine strict-import proof (fewer service tokens, one differing silent-unit selection); updated production job script requires a real smoke before claiming its complete flow passed. Original 180-minute standalone budget has about89minutes remaining; do not reset the accumulated budget without renewed authorization.

## Authorized continuation, 2026-10-12

User requested continuation. Studio restarted and same job retried; run132d5cc49af946bdb971f5c4e576f939 confirms87 scene cache hits and factual-stage reuse before new processing. Updated production CLI job script passed genuine packet auto-import and warm cache with one CLI call, then completed normally. Persona input4339tokens; actual production test CLI12.239s, output617 including496thinking. 26 exchange tests passed. First restricted pytest attempt failed creating Windows fixtures, not assertions; access-correct rerun passed. Start full-job independent runner only when cloud packets are needed with MaxMinutes89 to retain the cumulative approved180minute ceiling.
