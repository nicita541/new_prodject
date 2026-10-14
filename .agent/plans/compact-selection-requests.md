# Compact existing selection requests

## Goal
Send only relevant source facts and a compact output contract in existing DeepSeek disputed-selection requests. Keep accepted source proofs reusable, with no additional model check.

## Current state
Selection sends CURRENT images, before/after images, repeated ASR words/segments, old hypotheses, a long instruction and repeated per-unit schema branches. A measured current run used 47,192 input tokens and 4,435 output tokens in eight calls. The user cancelled that job; preserve its stopped state and accepted replies.

## Constraints
No paid requests for development. Preserve all source unit IDs, CURRENT frame indices/times, exact quoted speech, exclusions, context ownership and native result validation. Do not overwrite accepted request signatures. Work in the isolated source copy; verify the root baseline before integration. Keep source images intact. Full canonical contracts remain the cache lookup and validation contract; wire serialization is separately compacted.

## Implementation
1. Add an allowlisted selection-only wire serializer in the existing DeepSeek adapter: concise equivalent instruction, source-owned unit facts, relevant context speech/frame maps and unique prior descriptions. Unknown request shapes use the original route.
2. Losslessly factor repeated JSON schema dictionaries and serialize without whitespace. Preserve the original schema for local validation, discipline and legacy response-cache lookup.
3. Add regression coverage for unchanged source evidence, schema expansion equivalence, old cache reuse, response rejection and non-selection compatibility. Measure text size offline on actual saved requests.
4. Reconstruct the seven accepted stages offline under the updated adapter, preserve partial replies, integrate, publish audited snapshots and refresh idle Studio. Leave the user's job stopped.

## Validation
Run existing DeepSeek/selection/continuation tests and focused serializer tests. Offline comparison reports exact text bytes/characters and image counts, without estimating actual token or monetary savings. No provider dispatch is allowed. Verify live backend identity, ownership, cancelled status, economy and continuation settings after publication.

## Risks and rollback
Concise instructions must retain all native restrictions. Schema references must expand to the exact original schema; unsafe schema shapes use the original specification. Missing source data or unknown request format falls back unchanged. Cache fallback retains original full request bodies. Accepted proof is still checked against the full schema and native validators. Revert the adapter delta to restore previous wire serialization.

## Progress
- [x] Inspected current packets and identified redundant ASR/schema/hypotheses.
- [x] Implemented and verified compaction.
- [x] Published and verified the stopped production job.

Main verification passed 163 tests and 65 subtests. Twenty saved real packets shrank from 354,585 to 219,296 UTF-8 text bytes (38.2%); source images are unchanged and total-token savings are not measured. Offline reconstruction restored seven accepted stages; DeepSeek continuation reused 32 accepted replies, reached event 27/152 and stopped before the first unmatched request with zero new dispatches. Publication preserved existing cache entries, added 214 missing artifacts and backed up old stage/control/adapter files under scratch/compact-stage-backup-fc46976936b04a0d9eea3f082f7e8679. Fresh Product ownership checks confirmed the current backend, idle Studio, cancelled job, DeepSeek, economy enabled and continuation cache_only false. No production inference was resumed.
