# Goal

Resolve the reported failed montage by supporting the user's explicitly authorized additional review of missing source evidence, preserving accepted work and selecting the best whole native-valid answer. Do not lower confidence, fabricate evidence or add an episode-wide judge pass.

# Current state

Job cef8da9c-4a98-4284-b2e8-4ccd0870562d is failed at final_quality_gate.67 events pass source readiness;85 have insufficient evidence/confidence. Global relation recovery is blocked while source selection fails. Native adjudication caches valid negative decisions; sending a changed generic quality question can instead create a new request, while exact negative cache hits cannot improve. Retry loops previously mistook changed relation metadata for source progress; that local stop guard is already fixed. Two native geometry failures also affect first-frame start offsets and long indivisible words near the end.

# Constraints

All work/artifacts stay in F:/new_prodject. No model call until code/tests and a concrete bounded retry are ready. The user authorized rechecking missing fragments and choosing the best; accepted views must not dispatch. Whole answers are independently validated using original frame times, source ASR, exact unit coverage and unchanged .9 thresholds. Never compose semantic answers or raise confidence. DeepSeek and Antigravity use the same targeting/receipts; provenance/model remain explicit. No repeated paid requests after resume or uncertain transport outcome.

# Implementation

1. Back up changed sources and real job metadata/checkpoints before application.
2. Reuse prior native view proofs only with source, exact CURRENT geometry/ASR/frame hashes and native-validator agreement.
3. Add an explicit optional reassessment mode for failed views. Bind a persisted receipt to actual evidence/schema/native prompt, independent of changing diagnostic hypotheses or provider/model switches. Store actual producer identity separately. Reuse successful and unsuccessful completed reassessments; a dispatched receipt without an answer must stop rather than resend.
4. Rank whole validated candidates by acceptance then minimum native confidence, preserving original candidates/provenance. No third judge call.
5. Fix actual source geometry failures without weakening source-frame validation.
6. Integrate final-quality recovery with the explicit one-round path and preserve upstream completed stages through an audited offline migration before any restart.

# Validation

Fake-provider integration: accepted views0 queries; sparse failed view exactly1 new query; stronger/weaker/invalid/uncertain answers; warm resume0 new queries; genuinely changed source/evidence/schema changes the receipt contract, while timestamps and provider/model switches cannot grant another round; interrupted/transport-uncertain dispatch not repeated. Native request contains only one CURRENT view and necessary neighboring evidence. Real saved source proofs audited locally. Source offset/indivisible-word regressions. Run focused native quality/selection/continuation suites and offline native replay; report actual checks only.

# Risks and rollback

Model re-evaluation may remain unresolved: never promise semantic accuracy or accept its uncertainty as proof. New requests require genuinely missing evidence and may still spend tokens; one persisted additional round prevents cycling. Cache code identities must not be frozen. Keep original source files, stage records, evidence and receipts for explicit rollback; never overwrite old accepted raw answers under new question IDs. Automatic retries of unknown-charge outcomes are forbidden.

# Progress

- [x] Root cause/data audit and explicit user preference.
- [x] Source-view reuse/reassessment and geometry fixes.
- [x] Regression and offline saved-data validation:119 tests plus51 subtests; real event_0001 locally validates21 previous unresolved view candidates with0 requests. Frontend build, syntax and both smoke scripts pass.
- [x] Audited integration:10 original stage contexts matched verified pre-fix sources; isolated original/current native replays preserve identical outputs and unresolved/provenance fields with0 model requests. Published native replay passes; backups and report are in scratch/selection-reassessment-deployment/deployment-validation.json. A final metadata assertion initially mishandled Windows separators after successful publication; corrected and independently revalidated the published state without rewriting model answers.
- [x] Fresh server identity verified and one owned resume accepted as running (PID26292, recorded operation/result in scratch/selection-reassessment-deployment). No status, log or inference monitoring after acceptance. This completes the requested fix and launch; actual semantic recovery/export outcome remains unobserved.
