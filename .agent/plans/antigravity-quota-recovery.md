# Goal

Known Antigravity quota resets become a visible, cancellable automatic wait, preserving accepted evidence and continuing the same job without a manual restart.

# Current state

Episode job cef8da9c-4a98-4284-b2e8-4ccd0870562d stopped on quota at 15:48 UTC. Its official ERROR says individual quota resets in 2h29m4s. The packet is 9d1c8f124ce2ac85cb78bc213ab43ee0eb3f040f10bd4731d0779cf9e67d6c79. Existing code collapses quota/rate errors into a terminal exchange failure and discards the reset time. Native ERROR is correctly never accepted.

# Constraints

Reuse the user's chosen Antigravity/account/model. Do not bypass limits, change subscription, accept ERROR, repeat before reset, or overwrite accepted replies. Keep manual/external behavior, bounded retries, source cache identities and workspace-only paths. Preserve earlier stage indicators during cooldown.

# Implementation

1. Parse only a complete bounded provider reset duration, anchored to the recorded finished timestamp. Save safe structured reset metadata, including legacy diagnostics.
2. Persist an account-wide job exchange cooldown. The owned runner blocks new dispatch, drains existing work and stays alive. The worker waits cancellably, updates visible status and re-arms only failed quota control files after reset plus30s. Bound retries to2 per packet; archive failure metadata and retain all original requests, CLI attempts and accepted files.
3. Preflight known cooldown before pipeline restart; native exchange handles new quotas in-place without the600s response deadline expiring. Show automatic quota wait and local reset time in Studio.
4. Add clock-driven and real PowerShell regression tests for no early call, sibling preservation, cancellation, expired reset, unknown quota/auth, restart and retry cap. Deploy to the verified idle owner and resume the same episode into its real cooldown.

# Validation

Run focused quota/runner/exchange/progress tests and Studio lint/DOM build checks. Use short fake provider resets without real cloud calls. Verify the real episode stays owned/running, shows the correct timestamp, keeps accepted replies and dispatches nothing during cooldown. Full recovery after the real future reset remains separately observable.

# Risks and rollback

Provider quota remains external. Unknown/invalid reset or exhausted retry cap still pauses with a concrete reason. Clock parsing must not extend an old reset on reread. Workers must never delete accepted results or launch retries through a read API. Disable managed automation to retain manual policy; rollback only captured task files.

# Progress

- [x] Reproduced exact provider quota and captured current source baseline.
- [x] Implement safe persistent cooldown and UI state.
- [x] Verify and deploy.
- [x] Resume exact episode and confirm no dispatch before reset.

# Actual validation

228 tests and44 subtests passed, including a real PowerShell coordinator/fake provider wait31seconds followed by exactly one same-packet retry and native wrapper exit3 quota metadata. Frontend lint/DOM/bridge checks and build passed. Final BOM/cancellation corrections passed120 focused tests with25 subtests; deployed-root quota/progress checks passed45 tests with25 subtests. Six source-evidence component identities stayed exact.

Production verification found PowerShell5 BOM in legacy cli-run.json, which prevented initial cooldown migration; fixed bounded UTF8-sig decoding and regression fixture. The real packet was preserved as ERROR, enriched with recorded reset metadata, and the exact job resumed on the updated verified owner. At16:33 UTC its runner is waiting_quota with zero active packets; job remains running with six completed analysis passes and49/129 selection progress. Automatic resume deadline is2026-10-13T18:17:49.8096851Z (01:17:49 on14October in Novosibirsk). Real-provider success after that future reset and final MP4 output remain pending under the original automatic-processing plan.
