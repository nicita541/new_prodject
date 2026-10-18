# Focus the existing native check on source fidelity

## Goal

Reduce duplicated model work while preserving source-event/speech dependency and
actual cut-edge checks. The existing cut-only viewer owns story quality. No new
inference stage, model role, retry loop or confidence threshold is introduced.

## Current state

ADR0063 v2 asks the native model for whole-story criteria, three story proofs,
every retained utterance/dependency, all actual boundaries and all introduced
source gaps. The viewer separately repeats story criteria and three proofs.
The same real omitted fall was missed despite correct source images/transport;
paired navigation makes that omission visible but fresh repair review invents
another event in another gap. More formatting/prompt repetitions did not establish
semantic reliability. Ordinary paired-overview resume:122.898s/9newremote starts,
0accepted/3rendered drafts/0technical failures; exact warm5.641s/0newtransports.

## Constraints

Keep all source/timeline/frame/owner binding, actual-cut compilation, complete
physical speech intervals, gap observations, retained event-witness validation and
independent blind gating. The compiler cannot determine semantic question/answer
dependencies: native review still checks missing causes/answers/reactions against
original ASR/context. Preserve legacy absent/v1/v2 records unchanged. Keep v2 as
the default until the fixed negative and intact control demonstrate useful facts.

## Implementation

1. Add exact experimental source_join_policy v3, separately from default v2.
2. Native schema: resolved, joins, boundaries, required/requested units, blocking
   issues, optional notes. Remove duplicated is_story/criteria/proofs/dialogue.
3. Focus native prompt/payload on omitted original events/speech dependencies and
   every actual edge. Preserve the exact124original observations and paired
   navigation for the first comparison. Do not simultaneously shrink evidence.
4. Preserve one bound restoration OR blind trim, fresh source/viewer checks and
   existing audible strict-superset/duration/outer-bound guards. No second repair.
5. Require native source safety and independent viewer story approval in compiler;
   expose actual source checks without manufacturing legacy story proofs.
6. Only after explicit experiment results decide whether to switch the new-job
   default; retain old readers and exact accepted/negative/unknown cache policy.

## Validation

Pure tests: version/legacy isolation, complete once-only gap/edge coverage, actual
anchors/ownership, positive/negative edge decisions, uncertainty and dependency
requirements, static vs substantial change, continuous retained witness, stale
restoration evidence/one repair, and mandatory independent viewer. Integration
tests inspect the actual prompt/payload and preserve ASR without duplicate speech
proof output. No inference in tests.

Predeclare one v3 replay of the immutable ordinary defective edit/124observations,
and one replay of the54.00s bounded repair that retains the fall but leaves the
three other actual gaps unchanged (the prior native review invented a fall there).
This is a stronger specificity control than removing every gap in62.06s. Inspect factual
subject/state rows, not just status. A false story/event or approval of the known
defect fails this hypothesis. Preserve both results. No unchanged-question paid
repetition until approval. Ordinary-route/warm/editorial/audio/corpus acceptance
remain separate after any component success.

## Risks and rollback

Task simplification may not resolve false visual interpretation. Loss of semantic
dialogue checking would be a regression, so keep source dependency issues native
and final story comprehension independent. Versioned schema and prompt bindings
prevent v2 responses from silently becoming v3 approvals. Leave default v2 while
experimental validation is incomplete; reverting the new default requires no
historical-data rewrite. All model experiments use only the authorized120s source.

## Progress

- [x] Read-only independent design and duplicated responsibilities identified.
- [x] Pure v3 contract, compatibility and restoration implemented/tested experimentally.
- [x] Focused prompt/payload integration; combined211tests/153subtests passed11.81s.
- [x] Fixed real negative and fall-restored specificity controls executed once each.
- [x] Default decision: NOT adopted. Both controls need_review; restored control contains invented action/speech. Exact warm0newcalls.
- [x] Experimental code/tests archived with trial and removed from production; v2 remains. This plan's experiment is closed as failed, not a product completion claim.

Trial: temp/source-fidelity-controls-7d037bd8c411. Negative15.691s/124sameimages;
fall-restored13.564s/121sameimages; exactwarm3.446/3.399s. No new proposer/repair/
publication. Native output claims speech for silent u_7efaea50d40e46ee and compares
different visible subjects as an object-state change. Mechanism correctness does
not establish truthful image interpretation. See ADR0064 for archived code paths.
