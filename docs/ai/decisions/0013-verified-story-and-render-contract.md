# ADR-0013: Verified current-story ranges and bounded final rendering

## Status

Accepted

## Context

An independent story-stage review can restore a unit containing new current-episode action or an important reaction. Later closing, source-role, global-selection, pacing, or planner stages must not remove that evidence. The same pipeline also needs a safe way to reduce export time without increasing GPU-model or paid-provider concurrency, changing chronological output, or losing resumability.

## Decision

An omission proof creates authoritative current-story protection only when it has exact boolean `current_episode_story=true`, finite confidence at least 0.9, and positive new-action evidence or a reaction protected by the selected profile. Persist the proof and original unit bounds together; cache validation must reject missing, malformed, inconsistent, unselected, or out-of-event verified ranges. Owner-false OP/preview novelty and tentative fallback do not create authority. Later broad exclusions are subtracted around verified ranges, so confirmed nonstory spans remain excluded.

Keep GPU/model and paid-provider work sequential. After all model stages close, permit at most two independent final FFmpeg part renders. The coordinator owns progress, chronological commits, checkpoints, validation, and publication. Failure/cancellation stops new dispatch, cancels/drains owned subprocesses, and preserves validated completed parts for resume. Run manifests record source, Git/runtime-code and semantic identities plus stage/part timings; unknown legacy encoder provenance stays unknown.

Storyboard evidence is bounded by actual video-frame timestamps rather than the container/audio duration, and the source-bound probe is cached only for matching path, size, and modification time. Balance preflight failures are typed: one retry is allowed for transport or response-JSON parse failures before the paid reservation, while HTTP/authentication/insufficient-balance failures fail closed. If local pacing fallback is used, its result is stored separately with degraded provenance and cannot satisfy a remote-stage cache identity.

## Alternatives considered

- Let later stages independently decide whether to remove restored story evidence: rejected because the stages do not have stronger ownership proof than the independent story review.
- Treat any restored range as authoritative: rejected because fallback/uncertain restoration and novel OP/preview motion must not become current-episode story.
- Parallelize model or paid-provider calls, or render an unbounded number of parts: rejected due to shared GPU/accounting state and failure/recovery complexity.
- Keep rendering serial: safe but slower; bounded max-two export benchmarking showed lower elapsed time with matching decoded frames and SRT in the measured samples.

## Consequences

Verified ranges and proofs are part of versioned semantic cache state. Their validity must be rechecked on cache reuse and preserved through later edit stages. Production-credit removal additionally requires a typed visible staff/theme/series-title marker, matching source-sequence context, exact supplied speech when present, and skeptical independent confirmation. Sequence-edge reviews add bounded dense before/current/after samples, so a familiar character or office frame alone cannot confirm an edge. Final export concurrency is bounded and does not alter model-stage ordering or provider accounting. Run manifests improve timing and provenance diagnostics but do not establish editorial correctness.

## Revisit when

Change the proof threshold or ownership contract only with new source-review evidence and cross-stage regression coverage. Revisit the render worker cap if representative benchmarks or cancellation/resource behavior change; retain sequential model/provider stages unless their GPU and accounting ownership are redesigned.
