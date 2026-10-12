# Goal
Repair the stalled episode 1 job 00a9e488-dbe1-4614-9ec1-cf443e26083e, preserve accepted analysis, and resume only missing checks.

# Current state
The before-planner quality gate rejects source structure and dialogue coverage. Three conflicting arc groups erase every merged arc. Six partially unresolved dialogue batches discard their valid rows. Recovery repeats unchanged cached answers three times and presentation treats returning from a pass as acceptance.

# Constraints
Keep all artifacts under F:\new_prodject. Preserve existing unrelated edits, media, ASR, visual analysis and accepted provider replies. Never weaken proof/ownership gates or fabricate a finished export. The user authorizes targeted Antigravity checks only.

# Implementation
1. Localize arc merge failures and retain accepted dialogue rows from partially resolved batches.
2. Stop unchanged recovery loops and report actual validation status.
3. Run regression tests and replay the real saved answers without inference.
4. Recover remaining specific checks with the authorized provider and resume from existing checkpoints where possible.

# Validation
Focused pytest suites for structure, dialogue, quality recovery and progress; a saved before/after real-job report; actual resumed worker status and outputs if the source gates pass.

# Risks and rollback
Cross-batch disagreement must remain unresolved. Preserve original result files in a job-local recovery backup before updating them. Changes to code can be reverted separately from the user's existing edits; accepted transport replies remain immutable.

# Progress
- [x] Trace the real failure and reproduce the arc merge conflict from cached answers.
- [x] Fix and test localized recovery and progress.
- [x] Replay real cache and recover missing source roles and dialogue checks. Real recovered source gate passed with zero unresolved refs.
- [x] Build the real nine-part plan from recovered source; restore actual proved consequential action span and reuse bounded cached omission proofs.
- [x] Finish the remaining plan transitions and source endings, then export and validate real media in the same job.

The source recovery was published as waiting_analysis with an explicit pending-plan-check message. No completed or running worker state is fabricated. The original job metadata and source replies are backed up under temp/dd-recovery/original. Targeted continuity exposed a separate transport-budget bug: ManualVision returns UTF-8 bytes rather than tokenizer tokens. The manual continuity request now has its own bounded 24 KB ceiling; local tokenizer ceiling and every source gate remain intact. Regression tests cover both transport bounds.

All 17 transitions were checked against the original source. An independently rechecked restored event was a static title card rather than the cached claimed running action; native source adjudication accepted its removal. Only the restored bridge units received missing structure/dialogue ownership checks. Final source and nine-part plan gates passed, retained duration 917.859277 s. The ordinary native managed worker, gates, renderer and media validation exported nine MP4s and nine SRTs in the original job. A one-use temporary worker supplied a source-bound immutable verified analysis snapshot instead of re-running the episode; optional cover context was local extractive. Provenance is saved in the job's cached-recovery.json. Job status is completed. Focused verification: 224 tests and 172 subtests passed; relevant diff check passed. A previously confirmed unrelated Studio caption-visibility smoke failure remains outside this change.
