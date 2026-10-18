# 0054 — Independent short stories and immutable publication

Status: implemented foundation; opt-in rollout, real-video acceptance pending.

## Problem

Episode-wide condensation and partitioning can reject an otherwise complete
short story because unrelated footage is unresolved. Mutable checkpoints also
mix source evidence, selections and published output, complicating recovery.

## Decision

Keep the single FastAPI owner, managed worker, JSON persistence and existing
source-proof validators. Add a versioned `story_objective` contract. Missing
settings preserve `episode_condensation`; `standalone_shorts` explicitly selects
the new path. Its defaults are at most three stories, preferred 45–90 seconds,
and a hard 120-second ceiling. Count and preferred length never authorize an
incomplete story.

`discovery_regions` partitions the complete source into utterance-safe technical
regions using the survey's existing context/sampling bound. It performs no
model inference and makes no semantic-boundary claim.
Complete ASR segments and crossing word spans are indivisible owner envelopes;
long envelopes can exceed the sampling window and are explicitly flagged.
This preserves ordinary speech without claiming an ASR segment is a story beat.
`standalone_analysis` surveys these regions before detailed selection; the legacy episode-wide
semantic-boundary pass no longer precedes standalone discovery.
`episode_survey` batches sparse real source frames and exact ASR within image
and text context capacity. Long catalogs use complete chronological chapters;
global dependency review is explicit when its context cannot fit. Hypotheses
have no source-proof or export authority. `selective_analysis` analyzes the
union of requested original regions and prerequisites, retaining true source
neighbors and stable owners. It runs native selection/story/dialogue proofs
without the episode-condensation/global-retention chain. Unresolved owners do
not prevent qualified independent owners from receiving structural checks.
Native `unit_decisions_v2` carries one explicit keep/drop decision with the
existing grounded kind/frame/quote proof per source unit. Redundant legacy
lists are derived mechanically and pass the same validators. This objective
omits the overlapping story-refinement/choose-units pass; legacy routes retain
their existing contract and accepted records retain their original producer.
Physical actions/state transitions additionally require two distinct ordered
owned frames and concrete observed states before/after. The pair remains in
the native record and is rechecked by source selection and story-unit projection.
The historical v1 single-frame contract stays readable under its own version;
it cannot be promoted into temporal proof by inventing observations locally.
This verifies ownership/order of the model's observations, not their semantic
truth. A plausible description of movement still requires real source review.

`analysis_questions` reserves discovery and native unit-decision requests before dispatch.
Positive and negative answers are reused; an incomplete/failed reservation
blocks automatic resending of the identical question/evidence. Exclusive file
creation arbitrates independent instances. Request identities include source,
scope, exact prompt/schema/frame hashes and producer; no monetary ledger or
universal request count cap is introduced. Other native deep-pass caches
still own their exact request reuse; extending useful-question scheduling to
every native call remains a separate calibration/integration step.

`standalone_planner` compiles qualified source arcs independently.
Every candidate closes its own prerequisites, preserves source chronology and
passes native analysis, plan and final-quality checks against a source
projection. Ranking between clips is independent of episode chronology.
Unrelated uncertainty does not veto a candidate; required uncertain evidence
does. Declines and continuous-source draft proposals remain separate and are
not authorized for ready publication. If no ready candidate exists,
`standalone_drafts` may render only continuous-source review videos with the
whole frame and original audio. Separate immutable draft stores and file
routes keep these videos out of ready outputs. Their eligibility remains false
and the UI explicitly requires editorial review. Plan-only runs never render.

`pipeline` selects the objective and supplies existing export operations to
`standalone_pipeline`. The latter owns candidate compilation, per-candidate
render caching and publication, without importing the parent coordinator.
Native candidate plans retain part index 1; publication aliases their ranked
filenames, so changing rank alone does not re-encode media.

`candidate_framing` observes only final retained cuts. Its cached overlay owns
focus coordinates, not styled plans or semantic selections. Native geometry
is rechecked after overlay; uncertain portrait focus falls back explicitly to
the whole source frame. Planning and caption changes do not reopen completed
source discovery or restore stale captions from a framing cache.

StageJournal commits immutable source-qualified artifacts before replacing a
small stage pointer. Legacy embedded outputs remain readable. Physical
`source_evidence` snapshots are deep copies independent of editorial code and
selection. Corrupt artifact bytes are preserved; incomplete new manifests do
not fall back to stale embedded output.

`artifact_publication` stores exact plans, byte hashes, producing attempt and
decoder-validation version under `revisions/<digest>`. It copies verified
candidate renders once and commits `publication.json` last. Failed/cancelled
attempts preserve the prior committed revision. API metadata polls verify
manifests/plans and file geometry without streaming every video; downloads
verify current artifact bytes. An invalid pointer never falls back to mutable
legacy files. Legacy jobs without a pointer retain their old output route.

Ordinary and episode job creation optionally accept a canonical UUID
`operation_id`. A receipt reserves one job and its exact input/settings
snapshot before worker launch. Identical retries return that job; conflicting
commands fail. Startup recovery materializes an interrupted job without
launching models. Deleted committed operations do not recreate jobs.

`checkpoint_lineage` links incremental jobs explicitly by source SHA, source
path and owner. StageJournal, accepted replies and discovery questions can read
verified ancestors without copying their artifacts or changing their producer.
Unknown ancestor dispatches still block automatic repeats. Delete/prune guard
direct references, including reserved submissions before child commit. Legacy
source-level jobs retain their existing adapter; explicit episode references
must verify migrated library ownership throughout the chain. Legacy file-copy
adapters and large rendered-file reuse remain separate work.

Finishing reads the committed publication plan and can edit a prior publication
after a newer attempt fails. It never falls back to the mutable plan after a
broken publication. Published caption corrections use a source/candidate/cut/word
digest independent of public rank. Saves must echo that target, and queued
renders capture matching corrections. Re-ranking preserves corrections for the
same candidate; stale targets fail before writes. Unbound legacy rank records
are never adopted into published candidates. Legacy unpublished jobs keep their
existing caption adapter. The browser invalidates plans/captions together and
keeps unsaved old words separately in the current window. Invalid model/source contracts are reported as technical
failures separately from valid uncertain answers, while independent ready
candidates may still publish a partial result.

## Reliability and observability

Job/attempt/stage/candidate/logical-request/transport-attempt identities link
diagnostics and reported token use. Corrupt jobs are isolated, and worker
heartbeats measure process liveness independently of progress. A stale
heartbeat is diagnostic and does not kill a long inference. FFmpeg has bounded
bootstrap/stall/total deadlines based on advancing media progress. Fresh
exports undergo full decoding; legacy cache receipts are upgraded only after
real full decoding and then bound to video bytes.

Rejected DeepSeek length-exhausted output is a technical failure, without a
same-budget format retry. Source adjudication does not repeat JSON correction
already exhausted by the adapter. Source/model/request-bound negative native
checkpoints retain known contract/truncation failures across resumes; corrupt
negative bytes remain preserved and never authorize another dispatch.

Introduced one/two-frame gaps and islands are checked independently of natural
short source shots. Eyecatch position/duration heuristics now propose targeted
inspection and cannot clear selections. Model readiness follows provider and
layout; ordinary local sessions acquire the model only on actual use.

## Compatibility and limits

Deep qualification currently uses whole original touched regions. More precise
subregion scopes, calibrated question priorities, large rendered-artifact ancestry,
PTS/audio boundary refinements, managed finishing and actual-model/editorial
acceptance are remaining milestones. When the compact global catalog cannot
fit, distant dependencies remain explicitly unresolved. Sparse coverage is
not measured quiet-story recall. A local media trial rendered three real draft
videos in 8.77 seconds without model requests, fully decoded them and verified
the source hash. One inspected frame retained the complete source picture and
legible subtitles. This does not establish audio or editorial quality. Existing
feedback correction is not yet enabled for the standalone objective. No claim
of reduced real inference cost or release readiness follows from mechanism
tests alone. Keep the legacy default until product acceptance.

The controlled120s DeepSeek-plan trial finished in560.05s with28 local and55
remote requests, no technical failures,0 ready clips and3 rendered review
drafts. All50 native decisions passed their contracts and declared resolved,
but none passed the existing confidence threshold. This is a demonstrated
qualification-policy limitation, not evidence that their stories are safe to
publish. An unchanged warm run took8.51s with0 new transport requests. Provider
and output differences prevent an equivalent-workload speed comparison to the
earlier local trial.

Rollback selects the legacy objective for new runs. Immutable source evidence,
accepted replies and previously committed revisions remain available. Never
rewrite historical producer signatures to pretend they were produced by the
new implementation.
