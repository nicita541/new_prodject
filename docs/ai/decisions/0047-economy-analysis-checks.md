# ADR-0047: Optional analysis refinements in economy mode

Status: accepted. Date: 2026-10-14.

## Decision
New analysis jobs default to `economy_mode:true` in `analysis-settings.json`, with matching job/episode preferences. Economy skips additional global visual verification, pacing, silent-sequence editing, endings and the post-ending selection recheck. Matching already accepted optional outputs can still be restored without new requests. Source perception, credit/title handling, source roles, selected-range evidence, global story, source selection readiness, story/dialogue relations, required portrait framing and export validation remain active. Economy trades additional editorial refinement and independent visual rechecking for fewer model requests; it does not bypass unresolved source evidence.

`analysis_checks.AnalysisChecks` wraps the existing completed-pass journal. A skipped pass returns unchanged events, emits `skipped` and is never saved as an accepted completed output. Full/economy story/final cache identities differ. Turning full checks back on runs missing optional passes; exact accepted answers remain reusable. Plan-only jobs retain their parent analysis mode and have no switch. Historic completed jobs without the field remain represented as full analysis.

The processing switch uses `POST /api/jobs/{id}/analysis-checks`, delegating stop/update/optional resume to JobManager and episode persistence to Library. Active changes drain only the owned worker; stopped changes default to no restart. The Studio dims disabled pass rows and exposes the same choice before launch. The policy is included in the story semantic identity. Legacy contracts are reconstructed offline after this orchestration change rather than relabeling native cache signatures.

## Verification and rollback
Tests cover real optional dispatch suppression, core pass dispatch, accepted optional reuse, full/economy identities, disabled progress, ownership, stopped jobs, API/episode persistence and UI toggle/dimming. Revert source changes or disable economy to restore the full pipeline; accepted provider banks and source proofs remain intact.
