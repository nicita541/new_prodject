# ADR-0012: Persisted editorial policy and independent source-role proofs

## Status

Accepted for implementation; real-output editorial acceptance remains pending.

## Context

The user wants balanced, chronological condensation with almost all reactions/jokes retained, empty dwell and uninformative repetition removed, and current-episode plot after credits preserved. Reported OP/ED placement is a defect, not a placement requirement. ASR can recognize songs, title narration, or uploader commentary; blanket speech rescue can restore nonstory footage. Conversely, novelty-only pruning can erase an atmospheric reaction. Overlapping credit clusters previously replaced earlier exclusions and restored confirmed credits.

## Decision

Keep editorial intent separate from presentation/provider settings. `app/editorial.py` validates schema version 1 and policy `balanced-atmosphere-v1` in per-job `editorial-settings.json`, with boolean reaction/humor preservation and dwell/repetition removal flags. Persist defaults atomically only when absent. Add no UI control or automatic library-setting migration.

Compose credit-cluster exclusions once against original selections. Page-capable providers use the whole-sequence classifier; existing local/hybrid single-image routing remains available. After title/closing checks, `app/source_roles.py` verifies suspicious source units as current story, uploader material, next preview, title narration, song/artifact, or uncertain. A removable whole unit needs high confidence, no meaningful story/atmosphere, applicable exact ASR/visible evidence, and separate skeptical confirmation. Song/artifact claims additionally require the actual unit to fall inside a confirmed production sequence; a credit somewhere else in its event is insufficient.

Carry positive atmosphere IDs/ranges through closing, source-role, and pacing guards. Later speech-context restoration and planner handles subtract confirmed title/credit/closing/review exclusions. Uncertain or mixed role evidence preserves footage. Profile and source/model/context/stage identities govern compatible checkpoint reuse; the derived story identity also captures sequence version, context radius, and provider page capability.

## Alternatives considered

- Blanket ASR rescue restores narrator/title/song artifacts as story and cannot distinguish current-episode from promotional speech.
- Deleting all late footage, using fixed source timecodes, or requiring new plot facts loses post-credit resolution and jokes/reactions.
- Independent cluster mutation can revive earlier exclusions. Union against original input avoids order-dependent restoration.
- A new UI preference or library migration adds unrelated scope; the validated per-job profile provides explicit persistence now.

## Consequences

Independent verification adds bounded model work and proof checkpoints but keeps uncertain footage. No duration, removal, runtime, or spending quota is introduced. Existing provider routing, job/source ownership, cancellation, API reservations, ledger costs, and replay blocks retain their contracts. Technical checks cannot establish real-model editorial quality.

## Compatibility and rollback

Old jobs lacking the profile use balanced defaults when analyzed; their existing exports/media/annotations remain intact. Existing incompatible profile schemas fail explicitly rather than silently migrate. Semantic version/profile changes invalidate derived editorial decisions while independently matching preparation and response caches remain usable. Roll back the isolated source changes and recompute from preserved inputs; never delete old jobs, media, exports, ledger reservations/costs, or blocked request identities to force reuse.

## Revisit when

A future UI or profile schema change needs explicit library inheritance/migration, independent reviewers find a concrete false nonstory proof, or fresh/cache-backed outputs diverge under matching identities. See [the specification](../../specs/montage-quality.md) and [the independent review](../../qa/montage-quality-review.md).
