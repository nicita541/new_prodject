# ADR-0036: Separate story necessity from viewer interest

## Status
Accepted for implementation; editorial acceptance on a new real export is pending.

## Context
Reducing a nine-part montage to six parts lost perceived drive. The dramatic
planner rewarded speech occupancy and summed generic endings, while optional
source arcs inherited their parent scene's rank. This favors explanation and
routine question/answer closure and cannot distinguish several arcs in one scene.

## Decision
`viewer_interest` owns deterministic source-scoped scoring and shared editorial
instructions. The existing bounded `story_structure_pass` v8 assigns up to three
viewer-interest categories per CURRENT unit: conflict, escalation, reversal,
revelation, humor, emotional payoff, anticipation, character choice and skill
payoff. The existing confidence, concrete explanation and scoped proof citations
must support the assignment. Unknown interest is an empty list. The pass adds no
separate provider call and does not authorize selection or source exclusions.

The scorer validates source readiness, actual ASR, positive proof geometry and
exact inherited proof ownership. It counts only evidence overlapping the candidate
ranges. Existing accepted reaction/emotional/comedic proof kinds provide a limited
fallback for legacy analyses; legacy generic closure and narrative role labels do
not invent interest. Speech density supplies no bonus.

Story value is four times the greatest supplied event importance in the candidate.
Viewer-interest weights range from 10 to 16, with an eight-point fallback for a
specific reaction and a 32-point category cap. Each category counts once, regardless
of the number of events, labels or repeated proofs. A verified cliffhanger can add
at most 12 points; generic closure adds none. These are explicit editorial defaults,
not calibrated predictions of audience retention.

Both planners admit positively evidenced emotional/comedic beats even at low plot
importance. Dramatic retention ranks each optional source arc/unit by its own
score, preserving its supported setup/payoff and costing continuity first. Legacy
scene-wide groups cannot pull in low-ranked context through this rule. Part splitting
prefers a verified cliffhanger or evidenced payoff at the actual exit over routine
microdialogue closure. Word, response, consequential-action and final-quality gates
remain authoritative. A count preference cannot authorize an unsafe cut.

Score components, source references and explanations are stored in planner
diagnostics and allocation history. Scoring validates evidence once before
enumerating source-arc and boundary choices. There is no new media storage.

## Compatibility and rollback
Existing profiles, analyses and exports remain readable. Old analyses have no new
category labels and use only the constrained source-kind fallback. Structure v8
requests require the new field; schema/prompt and semantic identities invalidate
incompatible derived decisions. The interest module is included in selection,
structure, planner and ending identities; raw shot/media identity is unchanged.
Source ASR and original media can be reused. Existing exports are not rewritten by
reading or scoring a plan. Reverting this change restores the prior ranking.

## Alternatives considered
Changing only prompts leaves speech-density and parent-scene ranking biases in
place. Replacing the model or adding a separate interest pass increases runtime
without fixing those deterministic biases. Returning to a fixed nine-part target
does not express why a particular scene should survive.

## Validation and revisit
Authored provider integration covers a later interesting arc inside one parent
scene winning a quota while retaining its setup, silent payoff beating explanation,
foreign/stale/uncertain citations, zero speech-density bonus and mandatory context.
These checks establish mechanism behavior, not correctness of future model judgments.
Revisit weights and labels after comparing a new complete export against the old
and six-part versions, especially humor timing, buildup and part openings/endings.
