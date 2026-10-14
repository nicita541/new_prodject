# Safe DeepSeek / Antigravity switching

## Goal
Select DeepSeek temporarily for the same story work handled by Antigravity, and switch providers on an existing stopped or active job through one Studio action without losing source preparation or provider-owned accepted checkpoints.

## Current state
The existing endpoint accepts only local/Antigravity and refuses active jobs. It banks derived checkpoints but not source facts. Studio already defaults new jobs to DeepSeek-plan; episode «д» retains Antigravity and its latest job is cancelled. No worker is currently active. Worker quota initialization can still read retained Antigravity automation after changing provider.

## Constraints
Preserve original footage/ASR/audio/shots and semantic provider identities. Never mutate live worker files while it still owns model processes. Validate the destination before stopping the current worker. Keep existing endpoint stopped-only defaults for compatibility; explicit continuation performs controlled stop/switch/resume under the manager mutex. No new remote model job is automatically started during development. Work inside the isolated source copy with checked integration baselines.

## Implementation
1. Give JobManager one owned provider-switch operation and extend the current API to DeepSeek/DeepSeek-plan with explicit continuation. Bank story-derived snapshots per provider and retain factual preparation.
2. Ensure DeepSeek-plan and Antigravity share the local 4B perception path; only story/pacing transport changes. Gate Antigravity startup/quota initialization by the selected provider.
3. Add a provider selector and one apply-and-continue button on the processing screen, including active jobs. Keep the selected episode mode synchronized for future attempts.
4. Test manager lifecycle/retry failures, rejected destinations, reverse switching/checkpoints, quota isolation, API validation and UI flow. Synchronize documentation and set the affected episode to DeepSeek without automatically resuming a cancelled job.

## Validation
Portable Python pytest for jobs/API/provider/Antigravity/analysis regressions, existing Studio build/lint/bridge checks, plus browser inspection where feasible. Tests use fake owned workers; no cloud inference is sent by tests or migration.

## Risks and rollback
A provider switch may repeat provider-specific semantic checks; their accepted checkpoints are banked and reused only under validated identities. An in-flight request may be interrupted when its worker is stopped; accepted previous results remain. A switch failure must leave an explicit stopped/recoverable job, never a stale running state or another episode's terminated worker. Switching back uses the same action/bank; revert task-only code from scratch/provider-baseline.

## Progress
- [x] Inspected active application, modes and existing compatibility path.
- [x] Implemented owned switch and source/runner isolation.
- [x] Implemented Studio control and regressions.
- [x] Validated and integrated.
- [x] Applied temporary DeepSeek episode setting.

Final validation: working-checkout provider/Jobs/API/MCP/analysis suites passed 331 tests and 49 subtests (134.93s), with the two Windows stdio tests run separately outside the named-pipe-restricted sandbox (2 passed). Studio build, lint, bridge and DOM checks passed. The verified idle server was gracefully refreshed; series «д», episode 1 and cancelled job cef8da9c-4a98-4284-b2e8-4ccd0870562d now select DeepSeek-plan, retaining six Antigravity checkpoint groups and clearing the old quota wait. No inference/resume occurred. DeepSeek /models connection check reports available=true and vision_supported=true.
