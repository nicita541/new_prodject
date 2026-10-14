# Goal

Accelerate automatic Antigravity validation across the episode while retaining source evidence, spoken-word boundaries, independent confirmations, sequential story memory and reusable accepted answers.

# Current state

The current episode has completed titles, closing novelty, source roles and global visual checks. Selection is running. Scene refinement, global visual verification and selection already batch independent queries through a single coordinator. Titles, closing, source roles and ending windows still wait sequentially. Structure uses six units and dialogue twelve units per cloud call. Pacing decisions depend on previously retained material.

# Constraints

Keep manual/local policy unchanged. Never parallelize evolving retention or story memory. Preserve original full episode context and native schemas. Keep four producers and two official CLI children bounded. Work in the existing performance worktree; compare root baselines before promoting task files. Preserve all unrelated edits and source-vision cache identities.

# Implementation

1. Capture current source baseline; batch titles and filtered full-context closing/source-role reviews.
2. Batch independent ending proposal/confirmation windows, reduce results in chronological order and run planner fallback once.
3. Increase bounded cloud text capacity and increase readable pacing capacity without changing dependent decisions.
4. Verify native-output equivalence, request reduction, cancellation, cached resumes and nearby production tests. Document transport policy and limitations.
5. Promote verified files; safely resume the existing owned job with accepted checkpoints if deployment requires restarting its worker.

# Validation

Use repository pytest harness and native stage fixtures, exact query/schema/context comparisons, cold/warm transport counts and semantic component digests. Run relevant production entrypoint and quality tests. Inspect actual owned job status; do not claim final MP4 success before completion.

# Risks and rollback

Singleton calls must not lose neighbors, episode duration or retained context. Ending windows can overlap; chronological merge and one final fallback preserve native behavior. Keep dependent passes ordered. Roll back only changed task files against captured current baseline; batching opt-out remains available. No checkpoint rewriting or validation bypass.

# Progress

- [x] Capture baseline and inspect current episode.
- [x] Implement bounded independent checks and dependent-pass improvements.
- [x] Verify equivalence and reduced physical calls.
- [x] Promote, deploy and inspect continued episode processing.

# Verification results

373 tests and 149 subtests passed in the main stage/integration suite. After final transport and safety changes, 114 transport/entrypoint/quality tests, 131 native gate/progress tests with 61 subtests, and 38 pacing/batch tests passed in focused runs. Root deployment then passed 50 gate/progress/entrypoint/quality tests with 25 subtests. Source identities local_prompt, recovery, storyboard, scene_detector, global_story and continuity remain byte-exact. Read-only replay of four actual saved source-role requests reduced grouped prompt text from 21809 to 10570 characters; this is input sizing, not a measured full-episode speedup.

The exact owned episode was stopped only after its current provider output was saved, then resumed on the verified updated server at 15:39:24 UTC. Accepted files were not cleared or rewritten. Waiting for confirmation that its native warm checkpoints are reused and automated processing continues; final episode export remains pending under the earlier automatic-processing plan.

Confirmed live continuation: all 129 source scenes are cache hits. Story refinement, titles, closing novelty, source roles and global visual validation completed on the updated worker. Current selection adjudication reached 46/129 and remains running without an error. This completes the acceleration/deployment task; full export validation remains under the automatic-processing plan.
