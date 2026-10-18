# ADR-0057: Explicit immutable render ancestry

Status: implemented and integration-tested.

## Context

Incremental jobs copied lossless clean parts and MP4/SRT outputs into each new
job. Copying large media consumed storage and kept mutable render checkpoints
as the cross-job reuse boundary. Source equality alone cannot establish access:
jobs also belong to an episode and an explicit continuation chain.

## Decision

`processing.inherit_checkpoints` copies analysis snapshots, not `clean`, `render`
or `output` media trees. `checkpoint_lineage` is committed first and continues to
protect every ancestor from deletion/pruning while a dependent exists.

`render_ancestry` searches only that validated source/path/episode chain. Current
candidate quality checks still run before lookup. An exact per-part fingerprint
binds actual source SHA, cuts, captions, presentation, code, audio selection and
selected music bytes. Unrelated jobs are never scanned. A corrupt matching clip
is a cache miss; ownership or lineage errors fail closed.

Both initial render routes publish immutable revisions. Publication v2 binds job,
source and episode identity and can store an origin job/revision/file pair plus
the origin manifest hash instead of copying media. Public rank aliases need not
match the origin filename. Reading verifies every visited plan/manifest and the
chosen video's and subtitle's bytes, without reading unrelated origin media.
GET never upgrades evidence or repairs storage. The publication pointer commits
last; a failed attempt preserves the previous ready revision.

Clean parts use v2 identities, current source/artifact SHA256 and a receipt issued
only after full video/audio decoding. A matching ancestor clean file is consumed
read-only from its original path. Changing public rank or captions does not copy
or rebuild an otherwise identical clean montage. Standalone clean artifacts now
live at the job root, with content identity separating different candidates.

Worker entry and final publication refresh source hashing; repeated internal
reads can share the process cache. This handles Windows same-size source rewrites
with restored mtime, which creation-time `ctime` alone cannot detect.

V2 binds the raw job owner, so Library's additive legacy-owner migration does not
change immutable publication identity. The common ancestry validator separately
requires all known effective owners along the chain to agree; unmapped historical
source-level hops remain compatible while Library registers the new child.
Changing an explicit owner or introducing conflicting migrated owners rejects
reuse before source, clean or render caches can be read.

## Compatibility and rollback

V1 publications and untouched legacy output folders remain readable. Old clean
receipts lack decoding/hash proof and miss safely; no evidence is synthesized.
At this decision's initial implementation, snapshots still copied audio.wav.
[ADR-0065](0065-source-owned-asr-pcm-reuse.md) later replaces that copy with
validated source-owned PCM reuse and lazy preparation for its consumers. Initial
publication of a newly rendered file still copies it into the immutable revision;
this decision removes redundant cross-job copies, not every initial media copy.

Disable inherited lookup and render locally to contain a reuse regression.
Keep v2 readers while any stored references exist. Origins cannot be deleted
independently; deleting dependents first releases the existing chain protection.

## Validation

Mechanism tests cover rank aliases, transitive references, exact geometry/style,
read-only origin snapshots, corrupt media, source/owner/path changes, cancellation
and pointer failures. Generated-media tests exercise real clean full decoding and
child reuse with FFmpeg forbidden, plus published-reference HTTP GET/HEAD/Range,
SRT and deletion lifetime. Integration results are recorded in the active
ExecPlan; these checks do not imply editorial/audio acceptance of source stories.
