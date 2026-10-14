# Continue accepted analysis across story providers

## Goal
Changing Antigravity ↔ DeepSeek continues at the first unfinished analysis pass/query. Completed source perception and accepted semantic outputs remain reusable with provenance and input validation. Processing status must distinguish reading saved results from new inference.

## Current state
The previous switch banks provider-specific caches, but signatures differ across providers and the story coordinator stores only a final all-story snapshot. The resumed live job repeated local boundary inference and changed 129 accepted scene windows to 133. The job was explicitly stopped to contain this replay. It retains 129 continuous visual records with verified source image hashes and 1143 accepted Antigravity request contracts. The prior semantic run completed refinement/titles/closing/source roles/global visual verification and stopped during selection adjudication.

## Constraints
Preserve accepted answers and source windows without forging native cache signatures. Reuse requires exact source/transcript/settings inputs, request prompt/schema/image hashes, strict answer validation and real code identities. Keep provider provenance. Unknown/unfinished/corrupt results never count as completed. No cloud calls during legacy reconstruction. Resume the same user's job after verification. All artifacts stay in F:/new_prodject; isolate edits and check integration baselines.

## Implementation
1. Add job-owned neutral stage snapshots with input/code/output digests and producer provenance, plus a source-qualified exact accepted-request cache for partial passes.
2. Save/restore complete perception before opening 4B sessions. Import the legacy visual records only through an explicit, one-time audited migration, verifying coverage, source frames and ASR units. Preserve existing semantic identities; later code/input changes invalidate the neutral records.
3. Checkpoint story and editorial passes individually and decorate existing provider query methods without changing transport metadata/capabilities. Replay exact accepted replies; invoke only the chosen provider for misses.
4. Reconstruct completed legacy stages offline with a cache-only Antigravity adapter. Preserve partial accepted queries for DeepSeek to continue selection adjudication. Expose saved/replayed/new-request status in diagnostics/progress.
5. Validate source mutation, schema/image corruption, completed stages, mid-pass failure and bidirectional switching; integrate, refresh the idle server and resume the original job with observed first unfinished activity.

## Validation
Use portable pytest and existing Studio checks. Exercise actual saved source/contracts offline without inference and count reconstructed stages/reply hits. After user-authorized resume, inspect current request/phase telemetry; never infer job completion from startup.

## Risks and rollback
Legacy data lacks stage-wide snapshots; reconstruction may stop at the first unavailable exact contract. Preserve original provider banks and write separate continuation records, never relabel native model identities. A stale code/input context cannot be re-adopted automatically. A cache-only miss must stop offline reconstruction without starting agy or DeepSeek. Revert task source changes to the baseline and retain all original files and stage records.

## Progress
- [x] Characterized repeated inference and stopped the duplicate pass.
- [x] Verified all 129 original visual records and source coverage.
- [x] Implemented neutral stages/exact accepted requests.
- [x] Reconstructed and validated legacy continuation: 129 original scenes, seven complete stages; both provider dry runs stop inside the unfinished selection pass without inference. Antigravity's batch frontier is49/129; DeepSeek's scalar frontier reports event46/129 before the first missing exact request.
- [x] Integrated, resumed and inspected the user's job: accepted DeepSeek replies inside selection adjudication, progress115/129, no repeated local model activity. The user later cancelled the job while requesting a token-saving mode.
