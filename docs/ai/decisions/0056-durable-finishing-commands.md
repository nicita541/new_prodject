# 0056 — Immutable finishing commands and fenced artifact receipts

Status: managed worker/API/frontend integration implemented; broader acceptance in progress.

The previous preview/export daemon threads retained exact captions/cuts only in
in-memory arguments and re-resolved source/music/avatar during execution. A server
restart could not recover that original intention from status.json. Reconstructing
it from current settings would silently render a different command.

`finishing_commands.FinishingCommands` stores the normalized original request
separately from its frozen source/plan/captions/profile/asset parameters. Omitted
settings retain a saved-profile marker; they are not replaced with today's
profile for replay comparison. A canonical operation UUID serializes exact replay
and conflicting-payload rejection before mutable preflight or freezing. Reserve
complete command bytes, materialize command.json, then commit the operation
receipt. Recovery materializes reserved bytes only; it never starts inference,
resolves settings or automatically reruns rendering. Committed missing/corrupt
records fail closed, and tombstones prevent recreation of deleted operations.

An attempt token fences progress and part commits. A ready part receipt binds
command/part identity, actual artifact hashes and the renderer-supplied full-decode
validation version. Commit its immutable receipt before the per-part pointer.
Later attempts of the same command can reference that validated media without
copying it. The store does not decode media or manufacture validation provenance.
Cross-command presentation reuse needs an explicit compatible render identity.

`file_lock` contains the existing OS-backed lock and BusyError; `jobs` re-exports
the exact same classes. Command storage does not import or construct JobManager,
run startup recovery or acquire its server lifecycle lock. All store descendants,
including lock/command/runtime/attempt/receipt/part/media paths, reject existing
symlink/junction redirects before I/O. This does not claim resistance to a hostile
concurrent filesystem writer racing validation.

`finishing_render` freezes the exact source probe/selected audio stream, caption
ownership, style, resolved music/avatar and render-code/tool/font identity. Its
worker never resolves today's profile, source descriptor or asset choices. The
FFmpeg owner emits hashes after genuine full decode; recheck frozen inputs before
committing each new part and before completion. Same-job equivalent presentations
can reference an older validated receipt through a v2 part pointer. Exact source,
geometry/text, video/style, probe, resolved music/avatar and render contract must
match. Detect changed origin bytes, tampered pointers and reference cycles; do not
copy media. References share their whole job lifetime; no attempt-file cleanup may
remove a referenced origin.

`finishing_execution` schedules one owned process and two waiting commands.
`finishing_worker` waits for the parent's start gate before renderer imports or
FFmpeg descendants. Queue/attempt state is durable; startup materializes reserved
bytes, resumes waiting work, and marks lost running attempts interrupted. Resume
is explicit. Cancellation/shutdown stop the owned process tree and fence writes.
Heartbeat health is reported separately from process completion. Job deletion,
pruning and analysis check durable finishing ownership. Deleting a stopped job
retires all its operation intentions together and restores receipts on failed
removal. Legacy completed files retain their URLs; legacy interrupted tasks lacking
exact parameters are non-resumable. Legacy recovery happens at startup, never GET.

API submissions accept canonical operation_id values. Exact POST replay repairs
missing recorded materialization/enrollment/indexing before mutable preflight;
conflicts cannot alter the recorded operation. Read APIs stay read-only. Browser
retry identity survives ambiguous responses/reloads, with distinct identifiers
for changed/new confirmed intentions. The finishing screen loads server task
states and exposes resume/cancel of existing commands. File URLs resolve validated
receipt references, preserving prior base outputs and completed exports.

Validation includes authored storage/queue/API/browser fault tests and an actual
FFmpeg generated-video trial: stop after the first committed part, restart the
manager, mutate the current source descriptor/plan/captions, resume the exact
command, preserve the first file/receipt and fully decode both outputs. Spectral
measurement confirms the selected second source audio stream (880Hz rather than
440Hz). These checks prove finishing mechanics, not editorial/audio listening
acceptance of real source stories. Independent review found operation-lock,
post-commit enrollment and mid-render mutation gaps; these have targeted regressions.
Combined finishing/candidate/media/job verification passed539 tests and207 subtests,
including the permanent real generated-media process/API test. Rollback retains legacy readers and source/base
exports; do not delete command/reference records or their origin media.
