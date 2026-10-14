# ADR-0051: Scoped repair and exact request reuse

Status: accepted. Date: 2026-10-14. Extends ADR-0050 and ADR-0046.

## Decision

Repair existing checks at actual failed owners instead of restarting discovery or editorial analysis. `quality_recovery` orders geometry before selection and relations, then replans locally. Other problems from the old geometry wait for the next gate. Pure deterministic plan failures do not open a model session. Existing source and export validators remain mandatory.

`scoped_boundary_recovery` resolves persisted disputed boundary decisions against immediate real source segments. Proof identity includes source SHA, exact ASR/measured payload and actual frame hashes/times. Accepted, uncertain and rejected valid responses are reusable. A split reanalyzes only the intersection of the old CURRENT window and its new source owner. Unaffected IDs and proofs survive; new children inherit no deletion, relation, ending or focus authority. Downstream refresh targets those children and actual dependent owners. A source/transcript/shot/exact-event/code-qualified scene overlay preserves repaired ownership without replacing raw perception. Pending focus survives empty unresolved selection, later repair rounds and warm resume; it is completed outside the preceding model session before acceptance. Missing ownership/evidence stays unresolved.

`scoped_relations` reconstructs complete native story/dialogue aggregates locally. Only missing contracts within changed owners, actual relation endpoints and bounded source neighbors may dispatch. Contracts bind exact CURRENT/context source nodes, source proof checkpoints, available original image hashes, prompts, schemas and implementation. Original producer and raw decision hashes survive reuse. Persisted far endpoints are hypotheses selecting current source context, never new proof. Retired refs cannot remain accepted. Pending aggregates and opaque primary uncertainty remain explicitly unresolved until native verification succeeds.

Large global story maps use short reversible event IDs, a bound original catalogue identity, sparse nonempty dependencies and concise output explanations. Exact source summaries and native coverage/omission validation remain; decoded results contain original IDs. This prevents long repeated scope IDs and empty dependency records from exhausting the structured response budget.

Keep original cross-owner initial packing (structure three units, dialogue six, subject to native size limits). Recovery retains prior CURRENT cohort boundaries, so local insertion/splitting does not regroup the episode tail. Starting a request per scene would increase initial instruction/call overhead and was rejected.

`framing` caches raw model samples by actual images/times, phrase, schema and model/settings. Recompute held crops and fallback eligibility against current source geometry; a held crop is not independently observed model proof. A changed sample does not invalidate unrelated raw samples.

`scoped_ending_recovery` invokes the existing ending classification and independent confirmation only at a failed actual part boundary. Exact local dialogue is the cache dependency. Valid negative results also prevent identical warm queries. Endings carrying a context signature must still match current retained dialogue; equal reply IDs alone are insufficient.

DeepSeek performs at most one format-correction retry per adapter query and keeps the compact payload. HTTP/transport failures stop without automatic resend because server processing/billing may already have happened. Native source-validation corrections remain separate questions. Provider output limits are ceilings, not measured usage.

Automatic final-quality recovery also stops when the same source-selection/role owners remain unresolved and the actual source scope is unchanged, even if downstream relation diagnostics or coverage counts differ. Source scope binds ASR, event/unit geometry, accepted selected ranges, scene boundaries and confirmed exclusions. A failed decision's fallback selection does not change the full CURRENT units already reviewed and cannot alone authorize another attempt. Changed source scope or resolved/new owners remains eligible for the existing recovery policy. Source-selection failures take priority over downstream relation flags when routing repair. A stalled check stays unresolved and cannot authorize export. This guard bounds the current automatic recovery loop; it does not silently accept uncertain answers or promise zero calls on a separate explicit resume.

Typed reaction/emotional-pause protection follows `preserve_reactions`; comedic payoff follows `preserve_humor`. Ambiguous historical combined flags remain conservative. The user's balanced profile is unchanged. DeepSeek-plan and Antigravity remain interchangeable cloud choices for targeting and continuation; actual provider/model provenance and framing transport remain explicit. Completed snapshot manifests normalize only these two cloud provider choices, including equivalent legacy manifests; other providers and all source/profile/layout/content checks remain distinct.

## Compatibility and validation

Legacy graph rows without exact dependency contracts are not silently adopted as newly verified decisions. Completed early passes can be migrated only through explicit source/image/schema/input-chain audit, current native validator replay, preserved original provenance, offline continuation and backup. Immutable native replies are never rewritten under new question IDs.

Tests capture actual outbound queries and exercise local splits, far endpoints, exact warm reuse, corrupt proofs, uncertainty and stop conditions. They do not establish semantic model accuracy or a universal token saving. Compare actual provider usage only on comparable completed runs. Offline continuation blocks model starts and HTTP. Roll back task deltas and any explicit stage migration from workspace backups with Studio idle.
