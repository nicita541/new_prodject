# ADR-0060: Ground candidate proposals in original images before choosing cuts

Status: implemented; controlled editorial validation remains open.

## Context

The proposal request previously received an ASR catalog and an untrusted sparse
map hypothesis. Deep images arrived only after its chosen ending. Real proposals
included several conversational topics and unfinished tails, despite a visible
local outcome elsewhere in the same source context. Source and viewer gates
correctly rejected those edits, but could not reliably create a better proposal
from text-only selection.

## Decision

The existing `candidate_proposal` question now receives owned original images.
Sampling first covers original shots; locally prominent residual-motion pairs
provide additional before/after observations. The hypothesis stays explicitly
untrusted. Source-unit frame indices and actual image PTS bind pixels to the
unchanged ASR/catalog. No model stage, role, dependency or queue is added.

Sampling uses the provider's protocol page capacity (corrected for DeepSeek in
[ADR-0061](0061-deepseek-wire-capacity-and-paid-cache.md)). When more shot representatives
exist than can fit, chronological time coverage is retained before optional motion
detail. This is coarse proposal support, not proof that unsampled actions are
irrelevant. Exact native review still owns necessary source evidence and real
selection/boundary approval.

The local/external preflight remains inside the question reservation, after exact
positive/negative cache lookup. A proposal-only context miss can reduce its image
packet before any model transport; the capacity strictly decreases. Only this
known pre-dispatch result permits reduction. Provider contract failures and unknown
network outcomes never enter that loop. The native source check does not drop
required observations to fit. Cache-only/plan-only collection lookup precedes
decoding, tokenization and session acquisition.

Proposal observations are retained as private provenance. They do not grant
export eligibility or enter the independent reviewer as a verdict/justification.
Actual-cut source images are independently rebuilt, and the cut-only screen still
receives no omitted context, hypothesis or prior approval. Old accepted answers
are not rewritten; changed physical proposal questions use new identities.

## Validation and limits

Tests cover source image delivery in the existing request, reviewer isolation,
quiet-shot coverage, source ownership, unknown-dispatch stop and preflight
reduction followed by exact warm reuse without tokenization/query. A real source
proposal packet has 48 original images in three pages, compared with 143 images
for deep review of the same context. This is physical packet evidence, not a
measured equivalent full-run speed or editorial acceptance result.

Controlled proposal/native/viewer results and spending are recorded in the active
ExecPlan. Local-only text capacity, long/distant prerequisites, source survey
recall and actual listening/corpus evaluation remain separate acceptance work.

Original images alone did not fix the observed long unfinished proposal: its
source review approved, but the independent viewer rejected its final unfulfilled
request. Proposal instructions now select an observed local payoff first, work
backward to necessary setup/development, and stop after its required reaction
before an unrelated new topic/request. This adds neither a model call nor source
authority, and does not supply the failed example's verdict to the proposer.
The new prompt is a quality hypothesis, not a guarantee of discovery recall.

A subsequent ordinary-preference component trial automatically selected a56.61s
edit and passed both checks with3remote calls; exact warm repetition forbade
transport/local startup and made0new calls. The rendered published video fully
decoded. Prompt, preferences and available motion hints differed from the earlier
trial, so this cannot isolate prompt causality or establish full-source recall.
Audio was not auditioned; corpus/editorial acceptance remains open.

The independent output-only frames/SRT review then rated pacing2/5 and ending3/5:
the fall is retained but followed by about25s of aftermath. This component fails
the proposed editorial threshold despite both automated checks approving. Keep
that discrepancy explicit; successful proof/transport is not compelling Shorts
quality. Continuous playback and audio were not evaluated by that reviewer.
