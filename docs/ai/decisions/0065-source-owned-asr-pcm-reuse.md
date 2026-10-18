# ADR-0065: Reuse source-owned ASR PCM without snapshot copies

Status: implemented; mechanism and synthetic real FFmpeg integration verified.

## Context

Incremental/plan-only snapshots copied root audio.wav and the distinct temporary
media-evidence/audio.wav. Analysis also materialized root PCM even when completed
or provided ASR needed no audio read. Root ASR PCM is mono16/16k sample order;
perception PCM separately preserves packet PTS/gap observations and cannot be
substituted for it. Existing explicit checkpoint lineage already protects source,
ownership and ancestor lifetime; no new storage service or registry is needed.

## Decision

asr_audio owns preparation/reuse of the root signal. A producer writes its fixed
audio.wav and audio.receipt.json only after successful complete PCM validation.
Receipt identity binds source SHA, selected stream ordinal, existing extraction
identity, actual FFmpeg binary SHA, producer ID, file size/SHA and PCM format/frame
count. Hash current bytes rather than trusting size/mtime. Read every declared
frame in bounded chunks; truncated, empty or wrong-format WAV cannot be reused.
Recheck source and tool bytes after PCM validation before returning a cached path
or promoting extracted media: changes during extraction cannot issue a receipt
under the old identity. Restrict FFmpeg input protocols to local file/pipe.

Validate the entire existing checkpoint lineage before any PCM lookup, including
the current job's own cache. Resolve only current or explicit ancestor fixed paths,
reject redirects, and never scan equal-source jobs. Invalid lineage fails closed.
Missing/legacy/corrupt ancestor receipts or PCM miss safely; never create a receipt,
repair or alter an ancestor. Extract into the current job's partial file, validate,
then atomically promote. Cancellation/failure removes only the owned partial file.

Analysis resolves PCM lazily for transcription or repair and passes its returned
path read-only to inference. Completed/provided ASR skips PCM materialization;
missing provided ASR fails without silently starting a model. Both large WAV files
are excluded from snapshot inheritance; small metadata/transcript copying remains.
An inherited PCM consumer still follows the complete explicit lineage, including
plan-only intermediate jobs, so existing ancestor deletion protection applies.

## Compatibility and rollback

Keep inference.py and preparation_identity unchanged: the latter hashes the entire
inference module, so an input-only validation edit there would invalidate existing
automatic transcripts unnecessarily. Complete PCM validation happens at the new
preparation boundary before either inference invocation. Direct standalone inference
CLI truncation handling is outside this change. Existing accepted/provided ASR
keeps its historical provenance; no new audio receipt is fabricated for it.

Receiptless old PCM conservatively misses only when an actual ASR/repair operation
needs audio. Preserve old files. If ancestry reuse is disabled, extract locally;
no source/user media or historical receipt migration is required. This change does
not remove necessary first publication copies into immutable output revisions.

## Validation

Pure tests cover exact stream/extraction/source types, current bytes/tool identity,
full declared PCM reads, same-stat corruption, malformed/legacy receipts, redirected
paths, ownership/source/cycle/missing ancestry, cancellation and read-only parents.
Actual analysis preparation tests verify no PCM/model calls for completed/provided
ASR, one resolved path shared by transcription+repair, repair-only use and missing
provided input. Snapshot integration preserves metadata/transcript and skips WAVs.

A generated two-track video verifies actual FFmpeg stream1 selection at880Hz,
two-hop plan-only ancestry reuse with extraction forbidden, no WAV/receipt copies
and same-size/same-mtime byte damage recovered only in the new child. Artifact:
temp/asr-audio-ancestry-29dcda293d94. Extraction0.503s/reuse0.259s on that tiny
synthetic fixture are component observations, not whole-episode performance or
listening/editorial acceptance. No inference/remote requests were made.

Independent review reproduced a source-change-during-extraction provenance defect
in the first implementation. Post-validation source/tool rehash and same-stat
mutation tests now reject before media/receipt publication. The actual120s route
then resumed after this storage change in38.953s with remote/local inference and
ASR PCM preparation forbidden, preserving the same3needs-review drafts. That is
a post-code-change resume, not a same-code speed comparison or editorial success.
