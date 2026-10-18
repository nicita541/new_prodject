# Standalone Shorts acceptance protocol — v1

Implementation and model acceptance are separate. Passing authored mechanism
tests does not establish useful stories, quiet-story recall or inference cost.
The new objective remains opt-in while this protocol is incomplete.

## Corpus and isolation

Register two complete local episodes and four additional diverse real sources
when available. Bind every registered source to its actual SHA256, selected
streams, duration and a source revision. Do not substitute synthetic fixtures
for these six real sources. Synthetic media remains useful for technical
boundary regressions. Keep source paths, videos, ASR and model replies under
ignored workspace data/temp directories.

Each evaluation input contains only original video and optional ordinary ASR.
Expected story labels, editorial scores, suggested cuts, character states and
reviewer explanations stay outside the production input manifest. The existing
raw-quality harness rejects supplied semantic answers.

Use twelve short cases in addition to whole episodes:

| Case | Observation to verify |
| --- | --- |
| Quiet middle story | Sparse discovery notices meaningful silent action away from episode edges. |
| Independent later story | A later complete story can rank first while each clip stays chronological. |
| Distant prerequisite | Required earlier context is requested and proved; missing context blocks its consumer. |
| Question and answer | Complete relevant question/reply survive selection and native audio handles. |
| Mixed titles and story | Source-backed title exclusions preserve actual simultaneous narrative material. |
| Natural rapid shots | Complete short original shots survive; introduced one/two-frame fragments fail. |
| Tiny introduced gap | An introduced gap fails; the whole-candidate route may join an unspoken two-frame hole before review only if no exclusion is crossed and the native review sees that actual retained geometry. |
| Reaction and nonverbal audio | Emotional reactions, cries and action tails are complete without automatic pause cutting. |
| VFR and audio tail | Actual video PTS and a longer audio/container tail do not relabel nonexistent frames. |
| Unrelated uncertainty | Uncertain unused footage does not veto an independently proved clip. |
| Partial technical failure | A failed candidate is reported distinctly while verified independent outputs remain accessible. |
| No qualified story | Return honest declines/proposals; no manufactured ready file or forced clip count. |

## Cold and warm measurements

Run the same source/provider/policy on an isolated new job, then resume that
job unchanged. Record code identity before and after; a code change invalidates
the performance comparison. A new job does not imply flushed OS disk caches.
Measure cross-job incremental inheritance separately from same-job resume.

The workspace-local genuine local command is:

```powershell
tools/python/python.exe -B scripts/benchmark_local_pipeline.py --source <workspace-video> --directory <workspace-temp-run> --start-seconds 300 --durations 120 --timeout-seconds 1800 --standalone
```

Add `--resume` for the same recorded source, objective and job. This harness
forbids remote-provider HTTP, uses actual production callbacks and preserves
raw private request records locally. Its `complete` flag means the observed
technical/native gates passed; actual editorial review remains pending.

For an explicitly authorized cloud comparison, an existing raw input fixture
can use the same production observer with `--analysis-provider deepseek_plan`:

```powershell
tools/python/python.exe -B scripts/run_production_raw_quality.py --fixture-dir <raw-input-fixture> --job-dir <isolated-job> --standalone --render --analysis-provider deepseek_plan
```

This command can transmit ASR and selected frames to DeepSeek. Retain the
original cold outcome before observing the same job again; compare the warm
`new_transport_attempts` delta, not cumulative request totals. Rendered drafts
are review artifacts and do not make `complete` true.

Per attempt, preserve:

- Job/attempt IDs, exact source/code/model/settings identity and cache phase.
- Time to first **published** output, total wall time and stage durations.
- Logical requests, transport attempts, known tokens and unknown/incomplete
  responses by purpose/provider; do not add cumulative history to one run.
- Survey windows/frames, native source coverage and shared overlapping scopes.
- Accepted outputs, separate proposals/drafts, declines and technical failures.
- Encoder/decoder validation version, exact plan and output hashes.
- CPU/GPU/RAM/VRAM/disk samples and their attribution. Existing benchmark
  resource samples describe the whole machine, including other applications.

Compare identical component workloads separately from different product
scopes. Fewer exported minutes alone do not establish a faster equivalent
algorithm. Warm completion should not repeat completed source questions;
caption/music changes should preserve source analysis.

## Editorial review and fault acceptance

Watch each clip before consulting its source. Prefer two independent reviewers.
Score interest, standalone comprehension, causality, pacing, audio/action
completeness, ending and framing from 1–5. Then inspect omitted source and
record concrete defects. Model confidence is not an editorial score.

Proposed acceptance: comprehension/causality/ending at least 4/5, no critical
distortion, and no severe truncation or misleading reordering. Record severe
defects per exported minute and reasons for disagreements. Do not silently
lower this threshold to force three outputs.

Exercise lost submission response, corrupt job/manifests, interruption between
artifact and pointer, hung owned FFmpeg, provider/OOM failure, cancellation,
source/settings changes and damaged export bytes. A new failed revision must
leave prior committed media available. Technical errors must remain distinct
from editorial uncertainty. Rendered safe drafts, finishing recovery and
ancestor protection need their own completed acceptance before rollout.
