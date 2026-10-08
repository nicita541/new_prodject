# Goal

Show progress separately for each processing stage, with checkmarks for completed stages. Keep the current real DeepSeek job running and let the user review its saved result without Codex.

# Current state

The worker reports coarse overall milestones. Source-bound diagnostic checkpoints contain real boundary/scene counts. The running server cannot be restarted without interrupting its owned worker. Its existing `/assets` mount can serve a temporary presentation snapshot.

# Constraints

All files and helpers stay in the workspace. Do not modify semantic inference, source inputs, decisions or job state. Do not stop the current job. Missing counters must remain indeterminate. Provider, cancellation, failure and completed-review behavior remain available.

# Implementation

1. Add a read-only projection from actual stage reports and checkpoints to eight canonical stage rows. Expose it in the normal job response for future server starts.
2. Publish the same projection through the existing static mount for this already-running server, without writing job.json. Stop the helper at terminal status; preserve its snapshot.
3. Show each stage's real fraction/counter/phase, remove the overall percentage, and retain completed review links.
4. Verify projection/API behavior, React tests/build, and the actual running window. Preserve all source and outputs.

# Validation

Projection regressions cover duplicate/partial audit rows, missing checkpoints, re-entered stages and terminal errors. API checks cover progress exposure and failure isolation. Run the existing frontend test/build/lint commands and inspect the real browser. Confirm the worker and source cursor continue advancing.

# Risks and rollback

Counters describe the displayed current pass, not elapsed time or semantic acceptance. A new pass can reset its fraction and must show its phase. The temporary static snapshot must match job ID/stage/status and expire while running. Remove the UI/API projection and stop only its helper to roll back; do not stop the video worker.

# Progress

- [x] Confirm actual UI launch uses DeepSeek; old local attempts preserved.
- [ ] Implement read-only counters and temporary live publication.
- [ ] Integrate separate stage rows and verify the live window.
- [ ] Save validation/report and confirm independent result access.
