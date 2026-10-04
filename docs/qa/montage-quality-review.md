# Montage quality visual review

Reviewed 2026-10-04 from source-frame contact sheets and the saved ASR word timings for the confirmed primary episode. This is a sparse visual review, not full playback or final editorial acceptance. The sampled frames were viewed; no source audio was heard. The reported part numbers were not independently checked against a rendered export.

The opening/late-sequence sections below retain the earlier reviewer's sparse observations. A separate independent reviewer later inspected denser FFmpeg-decoded source frames; that review and its source-code checks are attributed explicitly at the end. Its denser preview evidence supersedes the earlier instruction to leave the late card uncertain, without establishing full OP/ED bounds or rendered-output acceptance.

## Opening sequence samples

The existing context sheet covers source samples from 65.90 to 208.00 seconds. I personally inspected the sheet. It contains:

- At 65.90–88.00, office conversation images.
- At 92.24–130.35, stylized character/art images with changing backgrounds. These sparse pictures do not establish whether every interval is opening footage or story footage.
- At 135.48, production/title text over character artwork; at 158.16, 168.75, and 176.25, further graphic/production-credit imagery; at 183.00, a title card over an image.
- At 187.00 and later sampled points, ordinary workplace/character scenes appear again.

The frames directly establish production/title text at the listed points, but do not establish continuous pure-credit bounds or a complete OP start/end. I have not independently confirmed the broader 88.167–183.300 interval. Do not apply that interval as an automatic exclusion from this review alone. The user's report that OP remains in part 2 is an output defect to resolve; this source sheet does not show the rendered part assignment.

## Late sequence and possible ED/preview

I inspected the source contact sheets for event 0033 and event 0034, plus locally extracted source samples for event 0035 at five-second spacing from 1390 to 1430 seconds.

| Source time | What I directly saw | Review label |
| --- | --- | --- |
| 1314.73–1333.93 samples | Night walk, imagined/graphic character imagery, and a convenience-store interaction | Story-like action is visible; these samples alone do not establish its relation to ED credits |
| 1337.39 | Staff-credit text over an animated background | Confirmed credit text at this sampled point; not a pure-credit interval by itself |
| 1340.53 | Screenwriter/director credit text over the changing image | Confirmed credit text at this sampled point; underlying interval remains mixed/uncertain |
| 1347.55 | Animation-director credit text over cigarette-related character imagery | Confirmed credit text interleaved with character imagery; do not classify the whole interval as pure ED |
| 1354.73–1393.78 samples | City view, commuters/passersby, store interaction, a close-up of the woman with a cigarette, and both characters together at night | Mixed montage with visible character interactions; current-story versus ED montage versus preview is unresolved from these frames |
| 1390–1423 samples | Male close-up, both characters smoking, a shared cigarette-related interaction, a package/offer, then the male in a vending-machine area | Preserve pending classification: visible action and interaction may carry episode story or atmosphere; do not remove as a quiet/non-event interval |
| 1425 sample | A separate graphic card reading “Вторая сигарета: Бодримся с тобой за супермаркетом” | Uncertain: it could be a title/end card or next-episode preview. The image and transcript do not settle which |
| 1430 sample | Black frame | End of the sampled source region; no further classification implied |

The saved ASR word list contains no word entries from 1390 seconds up to 1426.09 seconds. It then recognizes “Вторая сигарета. Бодримся с тобой за супермаркетом.” through 1429.07 seconds, with per-word confidence from 0.842 to 1.0. These recognized words match the visible card; they do not prove that the earlier section contains no speech, and I did not listen to the audio.

The frames provide point evidence for staff credits, character action, and the separate late card, but not exact continuous boundaries. Keep the 1425 card uncertain until source sequence context establishes whether it belongs to this episode or advertises the next one. Keep confirmed current-episode story after credits; exclude a next-episode preview only when it is identified as such. Do not infer that the whole post-credit portion is a preview.

## Review limits

- This review did not view a rendered short, verify that OP/ED was assigned to part 2 or the final part, or inspect the output audio/subtitles.
- Sparse samples do not establish all intervening frames, continuity, or whether an apparent reaction is humorous.
- No decision here changes stored jobs, source files, model outputs, or user annotations.
- For sign-off, review the fresh output and cache-backed rerun against this report and the specification; obtain denser boundary evidence where the classifier still conflates credits, current-episode story, and preview.

## Independent source-code review, 2026-10-04

Reviewer: the independent correctness-review agent (`independent_review`), distinct from the earlier sparse visual reviewer and implementation/QA owners. Review scope: changed analysis/story/production-sequence/closing/pacing/speech-context modules, new editorial/source-role modules, related tests, provider dispatch, confirmed exclusion composition, exact ASR evidence binding, conservative validation/fallback, and decision identities. This was a finite review, not an audit of the entire application.

The following concrete findings were reproduced with existing offline fixtures and supplied model responses, then corrected by the implementation owner and independently rechecked:

| Finding | Reproduction and impact | Correction/recheck |
| --- | --- | --- |
| P2: accepted disabled repetition/dwell flags did not govern earlier story/global omissions | With `remove_empty_holds=false` and `remove_exact_repetition=false`, a `repeated_information` decision still removed the 6–12-second speech unit; pacing could not restore it later | Story restores profile-blocked omissions; global selection receives/enforces the actual profile. Independent global recheck confirms no event exclusion when repetition removal is disabled |
| P1: closing novelty could undo explicitly protected atmosphere | A silent story event 0–20 with protected `u000`, followed by a confident no-new-facts response, became importance-1 ending footage with full closing exclusion | Closing version/profile identity, explicit atmosphere decisions, and prior protection guards now preserve the event as story/importance 4, without closing exclusions |
| P1: pacing could undo prior atmosphere despite a contradictory later response | Protected range 1–3 inside event 0–4 was removed by `waiting`, `story_change=false`, `reaction_or_humor=false` | An actual-range overlap veto and query filtering preserve known atmosphere. Independent recheck retains the complete 0–4 interval |

The final review found no additional concrete defects in the examined exclusion union, source-role quote binding/skeptical confirmation, actual-span song/artifact guard, speech exclusion precedence, provider routes, persisted profile, or derived/replay identity. This statement is limited to reviewed source and deterministic checks; it does not certify real-model classification or rendered content.

The independent reviewer actually ran:

```powershell
tools/python/python.exe -m unittest tests.test_production_sequence tests.test_production tests.test_story tests.test_pacing tests.test_speech_context tests.test_closing tests.test_analysis -q
```

Result: `Ran 116 tests in 0.706s` — `OK`. Earlier in the review, a narrower 78-test command passed; the 116-test result is the final independent focused gate. No paid API, GPU inference, download, or full-video processing was run by this reviewer. Generated fixture data stayed under the project temp directory; the later closing reproduction mocked filesystem writes. The full post-change QA suite is a separate owner's gate and was pending when this record was written.

## Independent dense source-frame review, 2026-10-04

Reviewer: `independent_review`. Primary source job: `928a9e13-a294-48f3-8231-09edd61bdf2b`, «История о перекуре за супермаркетом». Provenance: existing ignored workspace manifest `data/diagnostics/editorial-boundaries-2026-10-04/manifest.json`; independent FFmpeg `-ss` seeking and first decoded frames at requested integer-second positions. The reviewer personally viewed all five existing contact pages: `opening-tail.page01.jpg`, `ending-staff.page01.jpg` through `.page03.jpg`, and `ending-tail-preview.page01.jpg`. No frames/media were added or changed for this review; no source audio was heard. The gifted-girl reference job with prefix `013` was not visually reviewed in this pass.

These are sampled source observations, not automatic production timecode rules or checked montage-part assignments:

| Requested source samples | Direct observation | Judgment and limit |
| --- | --- | --- |
| 175–178 | Dub/staff card over the seated couple | Confirmed visible credits at these samples; images alone do not prove all underlying action is nonstory |
| 179–183 | First-episode title over smoke graphic | Confirmed title-card imagery; OP-to-title transition lies between the 178 and 179 samples |
| 184–186; 187–190 | Exterior building, then office scene | Title-to-exterior transition lies between 183 and 184; office story context visible from 187. The exterior's value requires surrounding continuity, not a building-category rule |
| 1310–1318; 1319–1323; 1324–1329; 1330–1335 | Man near the shop/walking, imagined chibi girls, register interaction and girl's reaction, then night walk | No visible production credits in these samples. Potential current-story humor/reaction must remain pending audio/continuity review; proximity to ED cannot authorize deletion |
| 1336–1342 | Visible production staff text over the animated backdrop | Confirmed credit markers; first sampled staff text appears after the 1335 night-walk sample. This does not prove a pure ED begins at precisely 1336 |
| 1343–1345; 1346–1348; 1349–1351; 1352–1359; 1360 | Backdrop, woman under credits, woman/lighter action, skyline, then man on train | Visible staff text at 1346–1348; surrounding montage membership versus current-story silent payoff remains uncertain without audio/sequence evidence |
| 1415; 1416–1422 | Split-shot farewell, then man's departure from the same shop | Preserve current-story farewell/departure evidence. Last sampled visible departure is 1422; no claim of exact action end |
| 1423–1425 | Empty shop frontage after departure | Possible empty dwell; adjacency alone does not establish removal value |
| 1426–1430; 1431–1433 | Explicit “Вторая сигарета” next-episode card, then black frames | Next-episode marker, distinct from the preceding current-story departure. Exclude confirmed preview/card; transition from empty frontage is bracketed by 1425/1426 samples, and from card to black by 1430/1431 |

Compared with the earlier sparse review, the denser decoded frames show empty frontage at the requested 1425 sample and the separate next-episode card at 1426 onward. Preserve both review methods/provenance; do not silently treat their different sampled timestamps as exact frame boundaries. One-second sampling brackets transitions but cannot verify every intervening frame, soundtrack, dialogue, or a whole continuous pure-credit interval. In particular, the broad 1310–1360 region is not authorized as an ED exclusion by this review.

## Outstanding output acceptance

Source review and dense stills are complete for this bounded pass. The separate QA owner subsequently ran `tools/python/python.exe -m pytest -q`: 354 tests and 134 subtests passed in 20.26 s, with one existing Starlette/httpx warning; its focused gate passed 107 tests and 33 subtests in 1.06 s. This is distinct from the independent reviewer's earlier 116-test gate. Source freeze identity, the fresh output and matching cache-backed rerun, rendered OP removal from part 2/ED removal from the final part, chronological last story beat, actual audio/subtitles, synchronization, continuity, and all specification criteria remain separately reviewable gates. No fresh/cache-backed real output or full playback passed in this independent review. Do not treat corrected synthetic tests, successful encoding elsewhere, or the visible preview marker as final montage quality sign-off.
