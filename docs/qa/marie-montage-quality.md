# Marie montage quality review

This report tracks the user's continued montage-quality request for the completed Marie job. Automated results and model/source diagnostics are evidence to guide review; they do not establish that the rendered episode is editorially acceptable.

## Target identity and limits

| Field | Current evidence |
| --- | --- |
| Completed job | `00c2f343-102e-4227-a6fe-93905ed76ae7` |
| Source label | `Механическая Мари ... Kikaijikake no Marie ... Episode 1` |
| Source duration / frame size | 1430.999342 s / 1280×720 |
| Source file identity | 154,916,888 bytes; SHA-256 `E1711CC00D62FA6998C572F27A7FEE758BE6D4D594850E2A7AA7716911DD8C63` |
| Rendered parts | 15; `plan.json` and `output/part_001..015.mp4` exist |
| Analysis / editorial profile | `deepseek_plan` / `balanced-atmosphere-v1` |
| Exact version/cut | Unconfirmed by user; do not assume title/name proves version equivalence |
| Historical implementation identity | Job-side source and semantic identities match the reviewed contract; exact historical runtime Git commit is unavailable. Reported defects therefore cannot be attributed to an older semantic version. |
| Audio, subtitle synchronization, full playback | Pending direct review |

The source file and job data remain in ignored `data/`. Do not copy private media, provider payloads, credentials, or settings into this tracked report. The supermarket episode remains the previous phase's distinct target.

## Continued user reports

The user reports that opening material remains at the beginning, a next-episode preview remains at the end of part 15, empty camera flyovers recur throughout, and a cut after a gap leaves an awkward scene tail in part 14. These are findings to reproduce against source and output, not ground-truth labels or timecodes. The quality target remains chronological and balanced: remove confirmed OP/preview and empty non-event dwell; retain meaningful quiet action, almost all short humor/reactions, and the intelligible cause/action/outcome of a scene. Review the part 14 gap and tail in surrounding source context before deciding whether it needs restoration or removal.

The user also asks for a faster pipeline. The approved candidate is at most two independent final FFmpeg renders after all model stages close. The coordinator must keep progress, checkpoint/reuse decisions, and output publication serialized and in chronological order. On failure or cancellation, stop queued work, cancel and drain owned subprocesses, and retain completed valid parts for resume. GPU/model stages remain sequential, and paid-request accounting stays unchanged.

## Existing output and source diagnostics

Job metadata confirms the historical target is completed and has 15 outputs. Its plan uses the balanced atmosphere profile. The sparse source-point fixture below evaluates plan membership only; no rendered source-to-output side-by-side review, audio/subtitle sync check, or same-policy cache comparison has yet been recorded here.

The quality implementation worker reports these source-level leads from the job's diagnostic material: an initial sequence proposal used unit U021 ending at source 104.312 s even though staff/theme and title imagery reportedly continued later; a visible-character witness alone must not establish the OP boundary. The preview reportedly begins at source 1419.846 s and continues to the 1430.999 s source end. In part 14, source time 1226.21–1234.11 is omitted between a repeated “Мари!” exchange and a selected eye-opening tail at 1234.11–1235, potentially losing the new wake-up action and leaving an incoherent tail. Dense source stills show the wake-up progression around 1228–1234.11, but the old Marie story stage predates the independent omission-proof feature; it did not produce the newer `current_episode_story` proof for this real job. The separate later-pacing defect was reproduced in a synthetic test unit spanning 6–12 seconds, not in this Marie job. These are implementation-worker observations from this exact job, awaiting independent audio and rendered-part verification. They are review coordinates only; do not convert them into production time heuristics.

## Acceptance ledger

| Check | Expected result | Status / evidence |
| --- | --- | --- |
| Confirm exact source version and match current output | Identify the intended cut/version before transferring semantic labels | Pending; filename suggests Episode 1, user is unsure of version |
| Opening at source beginning | Remove confirmed pure OP while preserving any interleaved story | Pending source/output boundary review |
| Part 15 ending | Remove confirmed next-episode preview; retain any Marie episode resolution after credits | Pending continuous boundary and context review |
| Empty flyovers throughout | Remove only intervals confirmed to have no plot or atmosphere value | Pending; enumerate affected source/output spans |
| Part 14 gap and cut tail | Keep an intelligible causal scene, including new action/outcome; avoid dangling partial action | Pending; inspect source around 1226.21–1235 with audio and output; worker lead only |
| Quiet action, reaction, humor | Preserve consequential silent action and almost all short reactions/jokes | Pending rendered review |
| Chronology, continuity, subtitles/audio | Parts remain in source order; exports, dialogue, subtitle timing, and source audio align | Pending technical media inspection |
| Fresh versus compatible cached run | Same policy/evidence/model identities yield consistent editorial decisions and render structure | Pending |
| Bounded parallel final rendering | Maximum 2; only after model stages close; actual wall-time benefit with identical decoded frames/SRT; failure/cancel drains and preserves valid outputs | Benchmark positive; focused and full regression suites pass; real-source editor review remains pending |

## Render benchmark (sample only)

The pipeline worker measured two 20-second cinema/accent excerpts under the same machine/settings, serially and with two FFmpeg workers. After correcting the NVENC probe from unsupported 128×128 to supported 256×256 dimensions, two-trial medians were **4.49662655 s serial** and **3.2740278 s with two workers** (1.373× faster for these parts). Decoded video frames and SRT matched in all four trial outputs. The CPU fallback medians were 12.6999471 s serial and 8.0544448 s with two workers. This measures only two short exports, not analysis, model inference, full-job wall time, or overall user experience. The parallel path remains subject to full-suite cancellation/order/checkpoint checks.

Additional speed-worker smoke checks used an offline deterministic fixture with a preserved real smoking-episode source (no model request): `run_job` exported two 50-second cinema/accent parts using NVENC in 8.520092 s total / 8.368357 s rendering. A compatible second pass completed in 0.134407 s and preserved all MP4/SRT hashes and mtimes. Two run manifests were written; a legacy encoder cache without provenance was not relabeled. A separate owned-process cancellation smoke launched two real FFmpeg tasks, canceled after 0.6 s, drained both in 0.799507 s, dispatched no third task, and committed no partial result. This checks the rendering/resume control path only; it is not a fresh semantic analysis, full episode rerun, or acceptance of either episode's editorial content. The recorded run snapshot identifies Git revision `b27176e1ddf1c75456ecf0438a29d0e33f132c31`; it does not include a Marie source review.

## Previous phase point-evaluation follow-up

The prior job `6c4f0191-e8f5-4fe6-8549-65822a04e3ec` belongs to the separate supermarket episode. Running `tools/python/python.exe scripts/evaluate_montage_quality_points.py --fixture docs/qa/montage-quality-points.json --plan data/jobs/6c4f0191-e8f5-4fe6-8549-65822a04e3ec/plan.json` produced **15/18 matching reviewed points**, with chronological non-overlapping ranges. Both reviewed preview points (1426 s and 1430 s) remain in the plan; the 1415 s farewell point is absent. The other 15 points match. This sparse point fixture does not establish continuous boundaries or overall editorial quality, and does not apply to Marie.

## Marie source-point fixture and historical-plan baseline

`docs/qa/marie-montage-points.json` records only points personally checked in the saved independent FFmpeg source samples and contact sheets. It checks observed opening branding/theme points, the wake-up progression across the part-14 gap, explicit 次回予告/episode-2 preview points, and quiet courtyard reaction-inset controls. Its unlabelled boundary candidates around 104.312 s and 832.8–837.74 s are review-only; the evaluator does not score them. It does not establish continuous boundaries, audio, or semantic story ownership. The fixture is valid only for source SHA-256 `E1711CC00D62FA6998C572F27A7FEE758BE6D4D594850E2A7AA7716911DD8C63`. The helper cannot enforce source identity from the plan JSON, so compare that hash to the new job's source before applying it.

I checked that the fixture/helper contain no credentials or provider payloads and ran the evaluator against the historical Marie plan using `tools/python/python.exe -X utf8 scripts/evaluate_montage_quality_points.py --fixture docs/qa/marie-montage-points.json --plan data/jobs/00c2f343-102e-4227-a6fe-93905ed76ae7/plan.json`. It reports **7/17 points**, with chronological non-overlapping cuts. The plan still includes the sampled opening-theme point at 17 s, omits wake-up progression at 1228, 1230.07, and 1232 s while retaining its eye-open tail at 1234.11 s, and retains all six scored preview points from 1419.846–1429 s. It preserves the three quiet courtyard reaction-inset controls at 836.28, 837.01, and 837.74 s. This is a read-only historical-plan baseline, not the upcoming fresh job, rendered-frame evidence, or user acceptance. Python's default Windows CP1251 console cannot print the Russian fixture text; run this helper with `-X utf8` (or equivalent UTF-8 stdout) for readable JSON.

## Verification work

The completed offline regressions cover explicit preview/uploader/title proof despite tentative broad atmosphere protection, genuine story/reaction preservation, independent full-sequence boundary correction, malformed or uncertain provider results preserving footage, and verified current-episode story ranges surviving serialized proof/cache replay, closing, sequence, source-role, global selection, pacing, and planning. Owner-false opening/preview novelty and weak proof do not create authoritative ranges. Rendering tests cover the maximum-two bound, source-order coordinator commits independent of completion order, checkpoint/reuse metadata, unknown encoder provenance for legacy cache, failure/cancellation drain, and no dispatch after cancellation. Test fakes make no provider requests.

Verification run from the frozen implementation:

- Focused integration command `tools/python/python.exe -m pytest -q tests/test_story.py tests/test_source_roles.py tests/test_pacing.py tests/test_closing.py tests/test_production_sequence.py tests/test_analysis.py tests/test_planner.py tests/test_media.py`: **155 passed, 28 subtests passed** in 12.52 s.
- Final full command after planner identity 9 and proof-cache consistency changes, `tools/python/python.exe -m pytest -q`: **376 passed, 140 subtests passed** in 19.03 s, with one existing Starlette/httpx deprecation warning.
- Added regressions reject integer lookalikes for boolean ownership and bool-as-confidence; reject a cached positive proof if its authoritative range is missing; verify an independent story range splits broad exclusions while the adjacent nonstory spans remain excluded.
- Semantic/cache versions in the frozen source: story 12, edge 13, source roles 3, production sequence 6, pacing 13, closing 5, global story 5, speech-context identity 4, and planner 9. These identities invalidate incompatible semantic decisions; they do not establish the correctness of fresh model classifications.
- The new two-second silent candidate precision schedule split a previously coarse source interval at 834.402–836.138 / 836.138–837.874, separating an empty lead-in from a reaction. The offline cached schedules changed Marie 56→89 rows and 19→20 batches, smoking 54→88 and 16→18, and gifted 134→166 and 34→38. These are potential batch-count changes from cached inputs, not actual paid calls or a cost estimate; there is no auto-delete based on finer timing.

Final acceptance needs a side-by-side review of the correct Marie source and all 15 output parts, with special attention to the beginning, part 14 gap/tail, and part 15 preview; inspect audio, subtitles, chronology, continuity, and a compatible cache-backed comparison. Keep each criterion pending until supported by that evidence. Full test success validates code paths and invariants only. Fresh semantic decisions, the current job's actual rendered output, audio/subtitle sync, visual continuity, and the exact source version remain unverified here.
