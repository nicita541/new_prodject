# Goal
Automatic montage selection balances factual story necessity with evidenced viewer interest: conflict, escalation, reversal, revelation, humor, emotional payoff, anticipation, choice and demonstrated ability. Avoid dialogue-density bias and generic question/answer endings winning over dramatic beats.

# Current state
The dramatic planner ranks parent events by importance, summed endings and speech occupancy. Source-arc allocation inherits the earliest parent-event rank, so unrelated arcs in a scene share its score. Story structure already infers source-unit roles and relations from validated ASR/frame proofs. Balanced and dramatic editorial prompts differ; the dramatic prompt undervalues reactions without plot consequences.

# Constraints
Work in the current clean `codex/dramatic-montage` checkout. Preserve source, accepted ASR, exports and source-selection/continuity/speech gates. No provider launches or global installs. New classification uses the existing bounded structure request. Old artifacts remain readable; absent new labels mean unknown, with a limited fallback to directly evidenced emotional/comedic source kinds.

# Implementation
1. Add a deterministic viewer-interest domain with bounded category weights and exact source-proof ownership. Store categories in the existing structure response, propagate their citations to events, version its checkpoint.
2. Remove speech-density bonuses; rank optional source arcs/units by their own supported interest and story value. Keep complete supported setup/payoff groups, account for mandatory context first and retain hard source exclusions.
3. Prefer evidenced dramatic exits over routine microdialogue closure; update editorial instructions in both selection modes. Expose separate score components and citations in planner diagnostics.
4. Verify source-proof rejection, legacy compatibility, budgeted selection and downstream gates. Document ownership, cache dependencies and rollout limits.

# Validation
Use workspace `tools/python/python.exe -B -m pytest -q -p no:cacheprovider` for focused selection, structure, planner, retention, identity and final-quality suites. Authored provider fixtures verify integration without claiming actual model judgment quality. Read-only comparison of the saved episode may illustrate new ranks; it must not alter saved plans or claim a new rendered result.

# Risks and rollback
Model categories remain judgments, not independently proven engagement. Reject missing/foreign/uncertain citations; cap additive bonuses and do not infer excitement from motion, silence or word volume. Revert source commits to restore ranking; existing outputs remain intact. Fresh structure decisions require the new schema/cache identity, while source media/ASR remain reusable.

# Progress
- [x] Inspect existing selection, structure and allocation contracts.
- [x] Implement category evidence, source-scoped ranking and ending preference.
- [x] Run relevant regressions and inspect saved-source ranking.
- [x] Document final behavior and limits.

## Outcome
The combined 21-file focused suite passed: 413 tests and 175 subtests. It covers
structure-to-dialogue/plan integration, selection/continuity/source exclusions,
speech handles, final-quality/pipeline gates, cache invalidation and module
boundaries. An initial legacy arc expansion regression was fixed by requiring
scoped source refs; the new required model field is included in the two authored
structure-provider fixtures. No frontend code changed, so no frontend build was
claimed or required.

Read-only scoring of the saved nine-part analysis evaluated 129 events in 0.076 s,
finding 37 with accepted emotional/comedic source-kind evidence. The bounded report
is `temp/viewer-interest-review/legacy-ranks.json`. This is a legacy evidence reuse
check, not fresh perceptual verification. No provider, render, job state or existing
export was changed. ADR-0036 records weights, cache scope and editorial acceptance
limits. A new full export and user review remain the next quality evaluation.
