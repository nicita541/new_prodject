# ADR-0059: Observe candidate source shots and motion, not every ASR pause equally

Status: implemented and component/source tested; editorial acceptance pending.

## Context

A real automatically proposed candidate retained 75 physical intervals, including
28 spoken and 47 silent intervals. The previous sampler asked for three images
per silent interval, producing 172 images and exceeding the existing eight-page
provider limit before native review. ASR pauses partition source ownership; they
do not each establish a separate scene or action requiring identical inspection.

## Decision

`candidate_analysis` keeps one owned midpoint per observed source unit, original
shot entrance/exit images and exact actual-cut boundary observations. Existing
measured source optical flow adds before/after images at a locally prominent
residual-motion peak inside each shot. A local quartile fence chooses sampling
targets; it never identifies an action or proves its completion. Camera-only
motion, pairs crossing a source cut, foreign/malformed perception hints and
semantic labels cannot authorize extra story evidence.

Requested-unit enrichment adds quarter points as well as entrance/exit images.
Previously a request concerning a silent interval often repeated the same three
already-observed positions. The existing coordinator dispatches another question
only when actual original PTS/image observations are genuinely new; physical
duplicates or exhausted units still stop without another model call.

Each extracted image retains its source interval, actual PTS and pixel hash.
The adapter's returned PTS is checked against the half-open owner before pages
or model input are created. Story proofs cannot borrow another interval's images.
Original ASR, semantic selection, native/source and cut-only criteria stay intact;
missing essential observations can still block approval or request local depth.
Provider page/text limits remain enforced. This is targeted observation, not
an increase in context limits or a semantic approval from motion scores.

Legacy cases and original accepted responses remain unchanged. Candidate code
identity invalidates changed qualification, while independent source survey/map
owners do not need new semantic passes for this sampler change. No new service,
model, queue or dependency is introduced.

## Validation and limits

Unit tests cover pause/shot sharing, exact cut ownership, prominent motion,
steady camera motion, quarter-point enrichment, malformed sampling hints and
early rejection of a foreign adapter frame. Real source extraction reduced the
formerly oversized packet from 172 to 143 actual owned images (eight pages)
without inference; this establishes capacity/ownership, not story quality.
Bounded ordinary native qualification is recorded in the active ExecPlan.

The same automatically proposed edit then reached both ordinary cloud checks:
the source reviewer approved it, while the cut-only viewer rejected its unfinished
ending. It is now a meaningful editorial negative rather than a context-capacity
failure. Exact warm reuse forbids remote transport and performs no new request.
This does not establish that the proposal itself was a good short.

Sparse observations remain imperfect for brief or subtle actions. Required-unit
requests, independent viewer checks and real editorial/audio evaluation remain
necessary. Long/distant prerequisite contexts can still exceed text/image capacity;
their semantic evidence cannot be silently discarded to manufacture an output.
