# ADR-0046: Continue accepted passes and requests across providers

Status: accepted. Date: 2026-10-14.

## Context
Provider banks preserve data but native signatures are provider-specific. Switching could repeat perception and completed story passes. Legacy Antigravity jobs have accepted request contracts but lack completed-pass snapshots.

## Decision
The same job owns `continuation/stages` and `continuation/replies`. Completed passes require matching video, transcript, shots, editorial inputs, real scoped code identities and output digests, and retain their producing provider. Analysis restores perception before opening a local model. Native caches keep their original identities and validators.

Partially completed passes reuse only answers matching source identity, exact prompt, schema and actual image hashes. Validate stored integrity and the current answer contract; normal domain validators still run. Decorate real adapter query methods, preserving type and capabilities. Dispatch missing requests through the selected provider. Interrupted or rejected answers never become completed snapshots. This works in both directions; in-flight requests cannot be transferred.

An explicit switch enables one-time legacy migration. Perception requires continuous original scene coverage, current detector/grouping versions, unchanged storyboard bytes, source-qualified CURRENT/context/recovery boards and ASR unit text. Legacy overviews may lack source metadata but must retain verified image hashes. Antigravity replies additionally require immutable request/result IDs, answer hashes and request image copies. Offline reconstruction has a cache-only mode which stops before unavailable answers or model calls. Never enable that mode for production. Changed inputs/code cannot silently re-adopt old visual records after migration.

## Verification and rollback
Regressions cover partial failures, changed inputs/code/source/schema/images, corruption, cancellation, batch misses, adapter identity and repeated migration. The user's stopped job was reconstructed offline from its original 129 scenes: seven completed passes were recovered without inference. Progress reports each restored pass and its producer. Revert source changes to disable continuation; original banks remain recoverable.
