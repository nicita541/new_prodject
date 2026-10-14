# Economy analysis toggle

## Goal
An enabled-by-default switch actually skips optional model passes, dims their processing rows and preserves core source, selection, story/dialogue and export validation. Users can switch back to full checks in the same job.

## Current state
Full analysis always coordinates global visual verification, pacing, silent sequences and endings. Core selection gates require positive source evidence and dialogue/story structure. The continuation feature now restores seven completed passes and exact replies; the live DeepSeek run progressed to115/129 and was subsequently cancelled by the user. Do not resume a user-stopped run automatically.

## Constraints
Keep accepted outputs and provenance, never mark missing source proof accepted. Preserve original windows and provider switching. Mode changes use the owned stop/update/resume operation. Defaults and active job settings must agree with the UI. All files stay within the workspace; isolate edits and verify baseline integration.

## Implementation
1. Add an explicit analysis check policy, with optional global visual recheck, pacing, silent sequence editing, endings and post-ending recheck. Completed matching optional results remain reusable without model calls.
2. Persist the setting for jobs and episodes. Expose an owned HTTP change endpoint. Resume only if the job was running or the caller explicitly requests continuation; changing a stopped job keeps it stopped.
3. Add the processing switch and dim disabled rows with clear descriptions. Include the setting in final/story cache routing so enabling full checks cannot return an incomplete economy snapshot.
4. Reconstruct accepted checkpoints offline after the orchestration code change, without model calls, then integrate and enable economy for the stopped current job.

## Validation
Test zero optional model invocations in economy, enabled full calls, partial failures/provenance, strict selection gates, default settings and lifecycle ownership. Run the existing frontend build/lint/bridge/DOM tests and focused portable pytest. Verify live saved setting and read-only progress; no unauthorized restart.

## Risks and rollback
Economy does less aesthetic refinement and independent visual rechecking. Retain core proof and speech gates. Code identity changes require audited offline reconstruction of accepted answers rather than forging native cache signatures. Switch off economy to run missing optional checks; preserve accepted caches and original banks.

## Progress
- [x] Defined optional checks and verified the current job is stopped.
- [x] Implemented backend policy, setting and UI; real economy dispatch suppression, persistence, ownership and stopped-job behavior verified. Frontend build/lint/bridge/DOM checks pass.
- [x] Verified, integrated and enabled for the current job. Main:154 tests plus45 subtests; frontend build/lint/bridge/DOM pass. Offline full reconstruction recovered seven passes; DeepSeek economy replay stopped at the first missing accepted query inside selection at114/129 without inference. Live API confirms economy=true for the job and episode, DeepSeek remains selected, status remains cancelled, server is idle. Production cache_only=false; original checkpoints and backups retained.
