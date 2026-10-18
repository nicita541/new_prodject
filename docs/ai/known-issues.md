# Known issues

Track unresolved issues only when they are real, reproducible, and useful across tasks.

For each issue record:
- symptom;
- reproduction/conditions;
- affected area;
- current understanding;
- workaround, if any;
- tracking issue/link, if one exists.

Remove entries when resolved; Git/issues retain the history.

## Quality acceptance still pending

Scoped boundary/relation recovery is implemented with exact native dependency contracts. Historical relation aggregates without these contracts cannot be silently treated as independently reusable scoped proofs. Such missing contracts remain explicit and may require an initial native mapping; this never authorizes whole-episode recovery outside the requested scope. New model judgments still need editorial acceptance on a real completed result. See [ADR-0051](decisions/0051-scoped-repair-and-exact-request-reuse.md).

Official agy1.3.3 stream-json supports only text blocks. Long text-only global review now uses verified UTF-8 stdin; image packets must retain tested CLI @ attachments and Windows argument-size splitting. A long-stdin image-only nonce test did not read the attached frame; an explicit image block was rejected before inference with0tokens. The packet script refuses overlong image input before paid launch. Do not raise image batch limits on the assumption that stream-json carries images. See ADR0030 and docs/antigravity-manual.md.
Genuine fresh120/180s local benchmarks both timed out around3600s at story condensation without a render. The user requires roughly30min for180s; these attempts fail that target. ASR takes about27–29s, while sequential9B requests and technical chunk fanout dominate. Future benchmark default is1800s; no quality gate was weakened. See docs/audit/performance-results.md and findings.md. A successful single Gemini packet is not full-series quality or speed acceptance.
The test episode now has a whole-frame/accent export with DeepSeek story/plan. User review exposed exact-ASR-end clipping, omitted replies in retained story scenes, and an opening tail in a mixed event. Speech handles/restoration and explicit confirmed exclusions fix these observed cases; the opening tail required manual verification of source frames. Long silent commute/office material and some closing/title material can still be retained when automatic classification is uncertain. Use the source timeline to compare kept and removed footage. Technical success does not establish editorial acceptance. See docs/quality-audit.md and .agent/plans/ready-studio.md.

## Small ASR errors remain possible
The test episode includes low-confidence isolated words and proper-name errors. Bounded gap repair fixed demonstrated timing/recognition mistakes, but no confidence threshold proves whether speech is real. Original audio remains intact. Review subtitles against the source; do not silently discard ambiguous words or invent corrections.

## Visual context remains over-retained
Separate replay e6726f9f-e118-48e7-8828-10fc5aa3ec47 keeps 1350.481 s (22:30) of 1420.222 s, versus first unattended 1197.228 s. Whole selected units restore necessary silent action but also inflate margins. Contextual pacing7 removes only 7.181 s; four invalid repetition-witness batches preserve the whole batch. Short gaps below .75 s are not reviewed, and frame-based judgments over-classify held reactions. Complete-summary/uncertainty guards correctly prevent unsupported whole-event exclusions but leave mixed redundant dialogue intact. This remains an editorial limitation, not resolved by balanced part lengths. Pacing8 now requires abstract narrative/emotional-function evidence; it is tested at the domain level but its model judgments are not yet checked by a new full export. See docs/ai/editorial-investigation-2026-10-03.md and this replay's qa/final-validation.json.

## Mixed story/uploader commentary survives conservative speech protection
Resolved in ADR-0018 via general `_is_dub_or_title_narration` filter: fandub studio announcements, translator credits, and episode title recitation are no longer protected as character dialogue in `_protected_speech`, allowing sequence cleaners and story condensation to remove them without episode-specific exclusions. The first unattended FumoDub result d2396ba0-ee65-4186-848b-eb64921a6aeb is preserved for regression comparison. Technical validation does not establish editorial acceptance.

## Scene threshold has limited calibration
Threshold 0.20 detects two transitions missed at 0.24 in six checked source windows. Ordinary motion reached 0.199887 in the same experiment; broad precision/recall is unmeasured. Periodic focus samples mitigate held crops but do not establish universal shot accuracy.

## Historical API accounting is retired
Runtime no longer maintains balance observations or money ledgers and does not impose an attempt spending ceiling. Historical accounting files remain on disk for reference. Actual provider charges must be checked in the DeepSeek account; successful-response caching avoids repeating completed requests.

## Original MKV playback depends on browser codecs
The timeline streams the original file without transcoding it. A browser may reject an MKV or an unsupported source codec even though FFmpeg can export it. Ready Shorts use MP4/H.264/AAC. Original-source comparison in that case requires a compatible local player; the source remains available in the project.


## Standalone acceptance and native qualification cost

The first local standalone120s trial took1741.563s,112 requests and383240 reported local tokens, producing0 ready files and3 draft proposals. Original code was stable. Six source/model contract failures were later identified inside unresolved native audits; they had been incorrectly absent from the outcome technical-failure list. Reporting now distinguishes those failures from valid semantic uncertainty. New technical discovery regions remove the24 pre-survey boundary requests observed in that trial, but their end-to-end recall/cost and remaining native fanout need a new controlled comparison. No reduced total cost or quality acceptance is claimed from routing tests. See temp/standalone-local-trial-followup.json and ADR0054.

The subsequent implementation uses one grounded unit-decision record instead of duplicated keep/drop/action lists and removes the overlapping standalone choose-units pass. Mechanism tests pass; its real cost and selection quality require the new controlled trial. Three continuous-source review drafts have been rendered and fully decoded locally without new model calls. Their separate stores/routes preserve ready publications; audio listening and editorial acceptance remain pending.

The controlled120s DeepSeek-plan trial finished in560.05s:28 local/55 remote requests,83662/219469 reported tokens respectively,0 technical failures,0 ready clips and3 rendered drafts. All50 native decisions passed their contracts and declared resolved, but none met the existing minimum confidence policy (minima0.55–0.85). No source owner therefore reached structural story checks. This identifies a policy bottleneck; it does not prove those candidate stories would pass editorial/source checks under another policy. Avoid inflating model confidence or simply lowering a threshold to force publication. Unchanged warm reuse took8.51s with0 new requests. Different providers and scope prevent a direct equivalent-workload speed claim.

Direct inspection of three native source storyboards also found a concrete ownership error: a physical-action record for frames4/5 described movement visible in frame6, which belongs to a different unit. Format validation alone did not catch that semantic borrowing. A technical discovery edge also split a complete ASR utterance at a word edge. Discovery now protects whole utterances plus crossing words; the new unit_decisions_v2 requires ordered owned before/after observations for physical actions and rechecks them before story planning. Legacy contracts remain readable without invented temporal proof. Neither this mechanism nor a model's resolved flag proves semantic truth; confidence policy and deep-view granularity still need product calibration.

Three targeted temporal cases through the ordinary DeepSeek-plan factory each passed the new contract with one request and no warm calls, but remained unqualified under the confidence policy. An earlier separate reasoning-enabled experiment exhausted generation before producing JSON and exposed nested correction fanout. Length exhaustion now stops at the same budget, source adjudication does not re-correct an adapter contract failure, and known native negative checkpoints retain the actual failure category on resume. These targeted cases are not whole-story, audio or editorial acceptance.

Finishing now binds plan reads to the committed publication and published caption corrections to their source candidate/geometry/words. Re-ranking keeps the same candidate's edits, while stale saves fail before writes. Managed finishing commands/processes, explicit resume/cancel and same-job validated media references are now integrated (ADR0056). Explicit immutable rendered references and verified clean-part ancestry now replace cross-job media copying (ADR0057). Extracted audio.wav still copies with analysis snapshots; moving it requires a source-evidence interface. Corpus/audio acceptance and adaptive action/audio boundaries remain pending.

New standalone jobs use source-only discovery and whole-candidate qualification (ADR0055), replacing mandatory micro-unit confidence gates for this objective only. The first candidate-only real continuation still produced0 ready clips: an unfinished proposed story was declined, and two native answers violated actual-ending/dialogue contracts. This is not resolved by successful schema tests. Dialogue targeting and first/last-cut evidence have since been made explicit; full-pipeline/editorial acceptance remains pending. Grouped source-frame extraction preserves exact original frame hashes/PTS and reduces per-interval process overhead, but no full-run equivalent-cost improvement is claimed.


The fresh whole-candidate full120s trial completed in137.439s with2 local and8
remote transport starts, rendering2 clips with partial status (one technical
micro-gap and two context-limited candidates). This differs from the older
workload and reuses the configured paid response cache; it is not an equivalent
cold speed comparison. Independent output-only frames/subtitles reviews found
unfinished endings in both clips. The cut-only screen and a single observed trim
are now mandatory, but their actual editorial acceptance remains unproven. The
reviewers did not audition audio. See ADR0055; do not treat native ready counts or
schema tests as product acceptance.


With the mandatory cut-only screen, the next fresh120s full trial finished in
147.761s with2 local/11 remote requests,1 accepted56.35s video,3 drafts and0
technical failures. Its full warm repeat took6.677s with0 new model transports
and unchanged output hashes. App code stayed fixed and paid response caches
were preserved. This demonstrates the new gate and reuse on this excerpt. Independent output-only
review scored comprehension/causality/ending4/5 with no critical defect; opening,
pacing and interest3/5. Audio was not auditioned. Full playback/audio and corpus
acceptance remain pending; see temp/blind-latest-review/review.json.

Measured audio-edge adaptation now runs before whole-candidate qualification
(ADR0058); it preserves source PTS/stream choice and never treats waveform valleys
as semantic completion. The subsequent fresh120s full run took245.172s with
2local/16remote starts,0ready/3rendered drafts/0technical failures: four candidates
failed the cut-only viewer check and one exceeded current deep-frame capacity.
Its different discovery proposals prevent attributing that outcome to audio alone.
Warm reuse took5.656s with transports/startups forbidden. A controlled earlier
useful proposal with the new geometry passed fresh source+viewer checks after
fixing ambiguous optional-notes reporting and produced a fully decoded56.17s
video. This component result does not prove robust full-run recall or listening
acceptance. Deep-frame context targeting, visual-action observation and corpus
audio/editorial evaluation remain open.

The old DeepSeek eight-page app restriction and expanded-schema false preflight
are corrected (ADR0061). Real nine-page source/eight-page viewer requests now
complete; that earlier long proposal still failed the independent viewer. A
separate ordinary-preference automatic proposal produced a fully decoded56.61s
component video with3remote calls and0new warm transports. Its changed prompt,
preferences and motion-hint availability prevent a causal comparison. Do not
generalize this success to whole-source recall, the unseen corpus or audio
listening. Optional diagnostic corruption can no longer invalidate paid cache.

Independent output-only frames/SRT review of that56.61s component rated pacing2/5
and ending3/5 despite source/blind approval. It preserves the fall but spends
about25s on aftermath; cinema layout also makes the action small. This is a
concrete gap between automatic story validity and compelling Shorts pacing.
The output does not meet editorial acceptance. Audio and continuous playback
were not reviewed. See temp/blind-payoff-output-review/review.json; this result
must not be reported as full quality success.

The later ordinary full-route resume returned a native-ready50.13s video, but
independent review exposed a real omission: source60.34–64.79s contains the rise
and actual fall (confirmed by original frames61.019/62.020/62.521s), while the
output jumps to aftermath near30.8s. Current safe retained-edge checks and three
story proofs do not prove introduced gaps safe. Both automatic gates missed this;
causal join/omission evidence in the existing source review is now required work.
Do not call the native-ready export editorially accepted. Preserve it for the
regression; see temp/blind-full-visual-output/review.json and
temp/full-fall-source-check/source-59.5-66.5.jpg. No audio listening was performed.

ADR0063 v2 now rejects that exact defective edit using its factual omitted event.
A controlled automatic restoration then passed fresh source/viewer checks and
produced a fully decoded62.06s video; warm reuse made0new model calls. This verifies
the bounded repair mechanism, not general omission detection or editorial
acceptance. Output review confirmed visible fall and causality4/5, but tempo and
ending3/5; no continuous playback/listening. The old export remains evidence.

The ordinary v2 resume still approved that same defective50.13s edit. No image,
index or transport mismatch was found: the model described an unchanged standing
male while ignoring the visible girl's state change. Gap-focused pages did not
improve that factual error and caused a schema failure; the experimental layout
was removed. Preserve both negative results (ADR0063). Full-route semantic
reliability remains unresolved; controlled repair success is insufficient.

Paired endpoint navigation now lets the ordinary run reject the known omission;
it returns3rendered needs-review drafts/0accepted/0technical failures in122.898s,
warm5.641s/0newcalls. Native interpretation remains unstable after repair. A focused
source-only v3 experiment also failed a fixed fall-restored specificity control,
including invented speech in a silent interval. Its code was archived and removed;
default v2 remains. See ADR0064. Do not present these negative outcomes as completed
editorial acceptance or keep replaying equivalent paid questions until they pass.

The pipeline now validates full declared PCM length and current bytes before ASR
or repair through asr_audio (ADR0065). Direct standalone inference CLI still reads
declared WAV frames without independently rejecting a shortened data body. A naive
inference.py input-only edit invalidates existing automatic ASR because preparation
identity hashes that whole file; address this separately with an explicit
compatibility strategy. Completed/provided pipeline ASR needs no PCM preparation.
