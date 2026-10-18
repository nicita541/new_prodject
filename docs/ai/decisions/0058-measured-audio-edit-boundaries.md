# ADR-0058: Measured audio boundaries before native qualification

Status: implemented; real-source qualification and audio acceptance in progress.

## Context

Fixed 0.18s lead and 0.55s tail protect ASR edges but cannot locate a non-ASR
cry, impact or decay. Existing perception's 500ms audio windows are too coarse
for such short edit adjustments. Amplitude does not establish what a sound
means, and optical flow alone does not establish that an action is complete.

## Decision

`audio_boundaries` measures the selected original audio track only near proposed
cut edges. Bounded source windows are merged before extraction. PCM is grouped
into uniform windows of at most 20ms across codec packets, retaining actual
`ashowinfo` source PTS and explicit gaps. Missing samples are not silence. The
decoder uses input seek and preserves timestamps; WAV sample order is mapped
through those measured packets, not a guessed zero offset. See the official
[FFmpeg seek/timestamp documentation](https://ffmpeg.org/ffmpeg.html).

Immutable JSON checkpoints bind source SHA, selected stream, requested windows,
code, policy and decoder identity. Current and explicit validated ancestor jobs
can supply an exact checkpoint; reading an ancestor never writes/copies its PCM.
Source-only survey/map caches remain independent of candidate boundary policy.

Pure compilation chooses nearby low-energy valleys relative to the local
20th/80th energy percentiles. A minimum 6dB local contrast (a factor of two in
amplitude) distinguishes a transition from steady background; digital zero can
also establish a quiet span. Three 20ms windows establish a stable observation,
not a semantic scene-duration threshold. The maximum 1.5s search reach retains
the existing bounded speech-repair scope. An unresolved longer tail is not
declared complete from these observations.

The selected semantic core remains intact. Omitted ASR words, exclusions, source
limits and missing PCM coverage remain barriers. Observations say whether a
measured transition was found; they do not label screams, speech or actions.
Uninformative steady audio keeps the existing safe geometry and an explicit
`no_quiet_transition` observation. No additional model pass is introduced.

Measurement and compilation precede original-source and cut-only qualification.
Both reviews observe the actual changed cuts and original frames at those edges.
Each saved case owns its physical audio evidence; recomputation binds the exact
timeline. Dropping the evidence under the new policy fails validation. Framing
must reproduce the same cuts. Trim repair measures/rebuilds before its strict
subset check, then gets fresh source and viewer checks. No approved timeline is
silently adjusted during export.

## Compatibility and limits

Legacy plans without this policy retain their original fixed margins. Existing
ready revisions stay readable. Only the new whole-candidate route requests these
measurements. Analysis failure remains a candidate technical error; no inference
is dispatched by GET, cache reads or a plan-only miss.

Local waveform measurements do not prove nonverbal or visual story completion.
Audio listening, adaptive action observation and diverse-source acceptance remain
required before claiming full editorial acceptance. ASR/perception still have
their existing audio preparations; consolidation into one source-audio owner is
separate migration work. Current edge extraction adds bounded local decoding,
not an additional whole-episode multimodal/model analysis.

## Validation

Tests exercise gain-relative valleys, non-ASR tails, steady background, omitted
words/exclusions, PTS gaps, old-approval rejection and exact framing rebuilds.
A generated two-track video verifies actual selected-track PCM/source timestamps,
full cache/ancestor reuse with decoding forbidden, and cancellation. The
authorized 120s source is measured separately from inference/edited acceptance;
costs and the full-route trial are recorded in the active ExecPlan.
