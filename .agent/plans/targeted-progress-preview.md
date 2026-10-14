# Goal

Show only the actual eligible work queue of each stage, with a queue ordinal rather than its source-catalogue position. Prepare and test the complete change separately; the user explicitly requires the current processing and Studio to keep running unchanged.

## Authorized deployment follow-up

The user subsequently explicitly requested applying all prepared changes, restarting the server and resuming the same job, with no monitoring afterward. This supersedes the earlier no-application/no-restart constraints below. The verified idle server was shut down through its native ownership handshake. Original progress sources and all ten accepted stage records/control were backed up before application. Applied-code regressions:134 passed +25subtests. Offline native replay also exposed a pre-existing cache-hit side effect: global_story_review set narrative_bridge during inference, while a stage hit returned only decisions. apply_global_selection now restores accepted bridge flags on both paths;49 tests +2subtests passed. No new check/model call is added. Complete native replay and explicit checkpoint revalidation precede server startup/resume. Do not monitor the processing job after the single accepted resume.

Deployment completed: all10 original stages validated against their original native keys/output hashes, then replayed through current native readers with identical final events and0 model requests. Audited records published with original producer/completion/output/unresolved metadata intact and full rollback backups. Fresh server identity verified; owned resume accepted status=running, server PID56276. No status calls, log following, inference monitoring or wake-up scheduled after that resume. Evidence is under scratch/targeted-progress-preview/{deployment-validation,resume-result,resume-operation}.json.

# Current state

Several producers report an index from the full event catalogue after skipping unneeded events. Parallel wrappers count every input, even when child refiners skip them. The presentation reader also repeats selected versus catalogue totals. Native relation recovery traverses a complete local aggregate although only explicit dispatch refs need processing.

# Constraints

All progress edits go to scratch/targeted-progress-preview, never live app/frontend files. No server/worker stop, restart, model calls or application of the progress patch. Preserve selection, cache identities/questions and source ownership behavior; only progress presentation/scheduling bookkeeping may change. Offline fake-provider tests use the staged app path through scratch.progress_preview_plugin. Record baseline hashes and a unified patch for later deliberate application. Later user steering separately authorized investigating and fixing a runtime error; that read-only diagnosis found the job had failed on event.importance=0 for a native excluded eyecatch. Only episode_profile.py and planner.py were fixed live, without restart/resume; all progress files remain unchanged live.

# Implementation

1. Stage current source and baseline hashes in the workspace.
2. Fix scalar and parallel eligible selection, specialist and visual queues without altering native results or context.
3. Fix scoped relation counters and presentation parsing; zero-target/cache paths must not advertise the full catalogue as pending work.
4. Run capture/regression tests against the overlay, assemble reviewable patch and confirm deployed fingerprint is unchanged.

# Validation

Sparse work at catalogue positions0/99 must display1/2 and2/2; no targets must send no model work and show no invented denominator; serial/parallel counters must agree; native requests/results and complete aggregate coverage must be preserved; scoped relation counters exclude unrelated retained owners. Use workspace Python with scratch.runtime_fixtures and the overlay plugin, without touching the actual running job.

# Risks and rollback

A local cache lookup can still be part of an eligible stage; displayed fragment work must never be described as paid request count. Dynamic native validation may discover more questions; do not invent a fixed future HTTP count. Preparing progress must not widen or shrink model scope. The preview is reversible by leaving it unapplied; later application requires baseline compatibility and preservation of completed checkpoints because current semantic identities also hash presentation code.

# Progress

- [x] Relevant skills, focused audit and isolated baseline.
- [x] Scalar/batch and scoped counters.
- [x] Overlay regressions and final patch: 625 tests and 281 subtests passed; git apply --check passed without applying.
- [x] No progress application; all original progress-file hashes unchanged. Backend difference is exactly the separately requested two-file eyecatch bug fix, proved by reconstructing the original fingerprint in memory. No server/job restart or resume.

# Separate runtime error

The saved job failed during analysis-result assembly attributed to the framing stage: native apply_eyecatch_exclusions assigns importance=0 and selected_ranges=[], while episode-profile and final planner validation required importance>=1. Both validators now allow zero only for this explicit excluded-eyecatch contract. Ordinary zero-importance story/filler, retained eyecatches, negative/out-of-range/nonfinite values remain invalid. 80 focused tests plus 64 subtests passed; actual saved episode profile rebuilt successfully for all152 events in memory with no model calls or job mutation. Checkpoints were neither relabelled nor discarded; later restart must account for source-hash identity compatibility.
