# ADR-0045: Owned DeepSeek / Antigravity stop-switch-resume

Status: accepted. Date: 2026-10-14.

## Context
Antigravity can be unavailable while a job has already prepared audio, ASR, source frames and accepted semantic answers. The existing mode endpoint allowed only Local/Antigravity and stopped jobs. Restarting with retained managed automation could wait for Gemini quota even after choosing DeepSeek.

## Decision
Use the existing processing modes and endpoint, with explicit `resume:true` for a one-action switch. `JobManager.change_analysis_provider` validates destination configuration, source availability and exclusive ownership before stopping a worker. The manager mutex covers draining only this job's worker tree, banking provider-specific derived snapshots, saving settings/job state and restarting the same job. Completed jobs and another active episode remain protected. Existing stopped-only behavior remains the default for API callers. Library owns updating the selected episode preference before restart. Product MCP verifies project/episode/job ownership and journals operation IDs.

Antigravity and DeepSeek-plan share local 4B perception. Story/pacing transport changes while existing framing/layout routing is preserved. The compatible checkpoint bank remains under the job's `antigravity/checkpoint-bank`, with provider namespaces now covering DeepSeek modes and final-analysis snapshots. Source preparation, original footage, model request caches and user planning preferences are never replaced from another provider's bank. Old banks containing planning preferences remain readable, but those entries are skipped on restoration. Each semantic checkpoint still validates its real provider/code/input identity; banked results are not silently declared interchangeable.

Worker exchange/quota initialization is conditional on the selected Antigravity provider. Persisted automation/quota settings survive a switch for future return, and do not run or delay a DeepSeek worker. An in-flight request may be interrupted; only accepted results are durable. New provider checks may repeat where no compatible checkpoint exists.

## Alternatives and consequences
Hot-swapping a provider object inside an active request or mixed independent batch requires changing cancellation, batch capability, token budgets and cache provenance simultaneously. The owned stop/resume path reuses the established process/checkpoint contracts and removes stale GPU/CLI children before changing transport. It has a brief restart cost and preserves explicit control over repeating provider-specific checks.

## Verification and rollback
Regressions cover forward/back provider banks, source/preferences, old watcher races, late terminal workers, missing configuration, bank/start failures, same-provider retries, completed/foreign jobs, API validation, MCP ownership/replay and DeepSeek quota isolation. Studio DOM/bridge checks exercise the selector, one-action continuation, browser plan invalidation and remembered episode choice. Switching back uses the same operation; restoring task source files reverses the feature without deleting data or banked answers.
