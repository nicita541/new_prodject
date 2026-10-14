# Automatic Antigravity processing and durable stage progress

## Goal
In project «д», episode 1, retain Antigravity and make a single start/resume run from saved source analysis through validated final output, without a separate PowerShell step. Preserve completed stage indicators while waiting for a provider. Report real failures promptly and retain checkpoints.

## Current state
Job `cef8da9c-4a98-4284-b2e8-4ccd0870562d` completed visual analysis and stopped at `choose_units`, packet `4d72933741030d683fac3d5592eb33cde04ad64470268013bda11b38d911ad98`. Its file automation is disabled. ManualVision correctly raises AnalysisPending; worker replaces the actual stage with waiting_analysis; stage_progress returns all pending for that noncanonical stage. The existing standalone runner already supports two independent CLI children, strict image reception/import, bounded error handling and cancellation. The user explicitly requested preserving Antigravity with automatic exchange.

## Constraints
All generated files/caches/logs remain inside F:\new_prodject; reuse the already installed and authenticated official CLI. Never read or expose credentials. Preserve source/media/accepted checkpoints and manual/external runner compatibility. Use the current isolated worktree and baseline checks. Do not promise absence of all future failures or replace semantic quality gates with automatic acceptance.

## Implementation
1. Preserve worker's actual paused stage and reconstruct legacy waiting stages from current-run diagnostic evidence. Test waiting/retry/failure states without fabricating completion.
2. Add a worker-owned runner lifecycle using the existing script and Windows Job Object; safe fixed arguments, checked paths, one runner lock, cooperative stop, early exit diagnostics and no orphan CLI processes.
3. Make new Antigravity starts use managed automation by default; preserve explicit manual/external modes. Show automatic operation in Studio instead of requiring a command. Add integration checks and document ownership/migration in an ADR.
4. Validate and deploy source/UI to the idle verified server, then resume the user's exact job and follow it through provider exchange and final output. Repair concrete failures discovered along the actual path, preserving valid work.

## Validation
Regression tests for progress at AnalysisPending and legacy waiting states, runner start/stop/duplicate/error/cancel behavior, explicit manual compatibility, input/response integrity, and Studio automatic controls. Use discovered Python pytest and portable Node build/lint/smoke commands. Exercise the real selected job; record actual completed stages, outputs and observed limits.

## Risks and rollback
External service/auth/quotas and model quality can fail independently of application correctness. Surface these causes rather than silently waiting or retrying charges without bounds. Worker owns newly launched descendants; never kill unrelated or externally started processes. Keep external file reception and manual import as opt-outs. Preserve provider packet identity and early4B caches; a runner change must not cause another full visual analysis. Revert only task patches if required.

## Progress
- [x] Identified the progress regression and disabled automatic exchange; received explicit Antigravity preference.
- [x] Implemented and verified progress and runner lifecycle: 208 tests and 40 subtests passed, including real PowerShell and a managed exchange end-to-end with a test CLI.
- [x] Built and deployed the automatic Studio flow; frontend lint/DOM/bridge checks passed. Fresh owner identity matches current source; server is ready and idle.
- [x] Reproduced and surfaced the initial external limitation on the exact resumed job: official CLI authentication failed before model work, both first packets reported zero usage. Four early stages remain completed and 129 scenes were cache hits. Managed automation is enabled; final outputs are not yet produced. The user subsequently supplied authenticated CLI evidence; the approved network restart removed the inherited sandbox proxy and native replies now validate automatically.

## Actual run and remaining validation
The job resumed via a fresh Product adapter using the same loopback owner and operation journal (the already connected MCP retained its previous expected hash). Actual managed process startup and two concurrent packet dispatches succeeded. Auth ERROR envelopes exited1 and were initially hidden behind generic process/batch errors; fixed classification, actionable batch messages and read-only explanation of legacy errors. The updated Studio displays the login cause and preserves the four completed stages. No credentials were extracted or authentication bypassed. See `scratch/automatic-antigravity/live-validation.json`. Full provider success, semantic quality and final MP4 export for this episode remain unverified until login is restored.

## Continuation after official login
2026-10-13: The user supplied a screenshot of the signed-in official CLI. Resumed the same job with a new operation ID. The new failures had zero usage and a sandbox-inherited proxy at loopback port9. With approved network escalation, restarted only the verified idle owner through its shutdown API and launched current Studio with that sandbox proxy removed; user proxy settings and persistent environment were not changed. Resumed the same saved job again. Full native provider/import/export validation is in progress; do not treat the earlier auth limitation as the current final result.

- [ ] Validate final semantic quality, plan and MP4 exports for the exact live episode after the automated story pass finishes.
