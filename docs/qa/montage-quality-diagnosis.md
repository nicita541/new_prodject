# Montage diagnosis, 4 October 2026

Read-only diagnosis against current source code, saved production decisions and existing source images. No inference, remote calls, renders or production decisions were changed during this diagnosis. Small synthetic checks used the bundled Python and mocked model/image interfaces. Generated fixture directories remain under `F:\new_prodject\temp`.

## Authoritative user intent

The questionnaire selects a coherent chronological condensed story and a **balanced**, tunable editing policy. Preserve almost all reactions and jokes for atmosphere, even without direct plot progress. Remove empty long dwelling and exact repetitions; keep significant silent causes/actions/reactions. The building flyover and rope capture are examples, not production object rules. Remove complete OP/ED and next-episode previews, while preserving current-episode story after credits. Quality has priority; no duration, time or API spending limit was requested. No arbitrary removal percentage or rule forcing all dialogue to remain. User subsequently explicitly confirmed the supermarket source as primary.

## Active sources and evidence

`data/library.json` currently contains two unarchived projects, despite the user's description of one visible active project. Do not archive or restore anything to resolve this discrepancy. The reported opening in part 2 matches the supermarket episode and existing handoff. Treat that as the primary candidate; retain the gifted-girl source as a regression.

| Source | Episode / representative job | Evidence |
| --- | --- | --- |
| История о перекуре за супермаркетом; imported filename `1 серия аниме «История о перекуре за супермаркетом» ⧸ «Super no Ura de Yani Suu» в дубляже от HikkiD.mp4` | episode `00fc6650-bb96-4179-810a-3f659c4462d8`; completed `928a9e13-a294-48f3-8231-09edd61bdf2b` | Pacing10, EDGE11 historical result. 15 parts, 1291.388 s retained. Source 169.800–183.300 remains in part 2: 13.500 s inside the earlier visually confirmed OP/title tail 157.530–183.300. Event_0004 retains 169.800–197.530. |
| Same source | completed `86b8f3bb-1072-4a10-a6da-d10d5764a20b` | EDGE9, pacing10, 1295.821541 s. Removes that particular tail interval, but the handoff explicitly reports OP elsewhere in part 2. It is not an accepted result. |
| Same source | cancelled `96088d6a-2e07-4e4f-ab75-898020a67912` | EDGE12/whole-sequence VERSION1. Handoff reports correct overall OP bounds 88.167–183.300 with false narrative exceptions U019/U020/U029/U030. Cancelled during local rendering; incomplete output is not a quality pass. |
| Забота об одарённой девушке; filename `Забота об одарённой девушке 1 Серия (Озвучка FumoDub) [-205217516_456241946].mp4` | episode `2f496c89-47d0-4a07-8234-a3e53a86c9d8`; completed `013efbd4-4adb-4f90-84df-a73d97b76b55` | Historical EDGE11, pacing10, 16 parts, 1360.582 s retained. Entire previously identified uploader/commentary interval 1330.230–1381.410 survives in part 16: 51.180 s. Saved warnings explicitly preserve finale speech. |
| Механическая Мари | `data/preparation/mari` | Handoff reports preparation only, no full production job. Broader quality remains unmeasured. |

The inspected screenshot is `data/jobs/928a9e13-a294-48f3-8231-09edd61bdf2b/qa/opening-context-01.jpg`. It shows a theme card at 135.48, staff/production text at 145.05/151.95, the continuation of stylized OP animation through 168.75, production/title text at 176.25/183.00 and actual office scenes after 187.00. Source times above are QA evidence only, never algorithmic exclusions. No fresh complete playback occurred in this diagnosis.

Older `docs/quality-audit.md` ends at pacing8 and does not describe latest code. Current state is recorded in `.agent/handoff-next-chat.md` and `.agent/plans/three-source-editorial-regression.md`: current EDGE13, whole-sequence VERSION2, pacing10. VERSION2 exception verification is not live-validated. The cited historical exports must not be presented as current VERSION2 results.

## Current call flow and causes

`pipeline.run_job` → `analysis.analyze`: preparation/ASR/shots → visual events → `story.refine_story` → `preserve_dialogue_in_credits` → `clean_credit_continuations` → `production.clean_sequences` → titles → closing novelty → global event review → `protect_speech_context` → pacing → framing → `planner.build_plan` → render.

- `production.py:113–115` routes image-page providers to `production_sequence.clean_whole_sequences`; `DeepSeekVision.supports_image_pages=True` at `deepseek.py:390`. Local and hybrid retain per-event/four-row handling. The whole-sequence implementation is connected; absence of its directory in EDGE11 jobs merely reflects historical implementation.
- `story.py:281–314` rescues >=8-word confident ASR or nearby question/answer speech as story, without classifying its source role. `_protected_speech` at 336–350 similarly ignores role. `production.py:156–159` skips protected units; `production_sequence.py:193` removes protected units from confirmed credit exclusions; `closing.py:230–233` restores long/confident speech. Uploader commentary, songs transcribed as dialogue, title narration and genuine character speech are conflated.
- Current synthetic ten-word subscription commentary with ASR probability .95 produced `_protected_speech=True`; `preserve_dialogue_in_credits` converted a pure ending into story importance4, retaining source .75–6.20. Word count/confidence cannot prove story role.
- `analysis.candidate_units` at 410–431 uses ASR ends and selected shot starts, not semantic action/setup/reaction boundaries. A reply finishing at 3 s makes units 0–3 and 3–12; the visual consequence after the reply belongs to a different unit. `story._ranges` at 48–64 preserves whole selected units, which protects action but inflates visual margins.
- Global review at `analysis.py:486–556` sees event summaries and can delete only whole events. It cannot reliably remove a repeated exchange from an event containing a unique fact. Full summaries and incompleteness guards are already implemented; do not undo those protections or lower confidence to mask missing evidence.
- `pacing.silent_units` at 62–93 excludes all speech handles and only reviews gaps >=.75 s, splitting into <=4 s units. Pacing10 supplies five current views with separate before/after context; movement alone does not prove narrative function. No current full playback proves its semantic judgments correct.

## Confirmed overlap bug in current whole-sequence code

Original credit clusters extend one event on either side. Two separated clusters can share an event. At `production_sequence.py:200–209`, the second cluster may rebuild a rescued/pure window from the full event and overwrite `excluded_credit_ranges`, losing the first cluster's confirmed removal. This reaches the deterministic planner, not only intermediate selected ranges.

Executed the following harness through PowerShell as a here-string piped to `& .\tools\python\python.exe -B -` from the workspace. It mocks imagery and model answers; no paid calls or source-specific production rules:

```python
import copy, json
from unittest.mock import patch
from tests.test_story import edge_fixture, FakeVision
from app.production_sequence import clean_whole_sequences
from app.planner import build_plan
folder, base, _ = edge_fixture(start=0, end=30)
events = [{**copy.deepcopy(base), 'id': f'event_{i:04d}',
           'start': i*10, 'end': (i+1)*10, 'focus': [],
           'selected_ranges': [{'start': i*10, 'end': (i+1)*10}],
           'credit_montage': False, 'credit_dialogue_rescued': True,
           'contains_credits': i in (0, 2)} for i in range(3)]
def answer(first):
    return {'kind': 'opening', 'first_unit': f'U{first:03d}',
            'last_unit': f'U{first:03d}', 'before_unit': f'U{first-1:03d}',
            'after_unit': f'U{first+1:03d}',
            'anchors': [{'unit': f'U{first:03d}', 'type': 'theme_credit',
                         'visible_text': 'Theme music'}],
            'narrative_units': [], 'confidence': .95,
            'boundary_evidence': 'Theme between chronological story scenes.'}
verified = {'confirmed': True, 'confidence': .95, 'evidence': 'Visible credit.'}
vision = FakeVision([answer(2), verified, answer(1), verified])
vision.model = vision.projector = 'test'
vision.thinking = False
shots = [{'start': i*5, 'end': (i+1)*5} for i in range(6)]
transcript = {'words': [], 'segments': []}
with patch('app.production.sequence_sheet', return_value=[folder/'page.jpg']):
    output = clean_whole_sequences(events, transcript, shots, folder,
                                   vision, lambda *a: None, lambda: False)
plan = build_plan({'probe': {'duration': 30, 'width': 1920, 'height': 1080,
                            'has_audio': True},
                   'events': output, 'transcript': transcript, 'shots': shots})
print(output[1]['selected_ranges'], output[1]['excluded_credit_ranges'])
print([(c['start'], c['end']) for p in plan['parts'] for c in p['cuts']])
```

Observed: shared selected range10–15, excluded range15–20; final cuts0–15 and20–30. First confirmed cut10–15 is restored (5 s). Fixture: `temp/story_b1f72e45c26e4be3873515d95388e0eb`. This reproduces a current contract defect. It does not prove that this particular overlap caused the user's real episode error.

## Cache identity finding and its limits

`analysis.py:624–629` includes EDGE_VERSION but not the independent `production_sequence.VERSION`, provider image-page capability or selected editorial policy. The whole-sequence inner checkpoint includes VERSION, but `story-events.json` can bypass that stage. Current VERSION2 also bumped EDGE12→13, so a stale final VERSION1 reuse is **not proven today**. This is an invalidation dependency that should be made explicit and regression-tested, avoiding fragile coupled manual bumps. Source/ASR/shot facts and compatible paid-response accounting must remain reusable.

## Isolated fix surfaces and verification

1. `app/production_sequence.py`: collect unioned confirmed exclusions across original clusters; apply once to original source ranges. Preserve genuine verified narrative exceptions. QA owns overlap-to-plan regression and replay/cancellation/edge/false-anchor tests.
2. `app/analysis.py`: explicit sequence/role/policy/capability identity helper, with no source names/times. QA verifies each semantic version/policy changes derived decisions while factual checkpoints survive.
3. `app/production_sequence.py`, `app/story.py`, `app/closing.py`, `app/speech_context.py`: independently classify character/narrator-current-story versus song/title/uploader/preview; maintain affirmative visual/context evidence and uncertainty safeguards. Confirmed nonstory ranges must survive speech rescue and planner expansion. Genuine post-ED events, questions, short replies and silent payoffs must remain.
4. `app/pacing.py`, local story selection: balanced policy grounded in narrative/emotional information, retained repetition witnesses and current images. Delete irrelevant building hold, preserve changing capture/cause/reaction; no object heuristic, fixed output duration or blanket dialogue retention.

First run focused synthetic/domain tests; then the primary source with compatible preparation/validated response reuse, preserved previous outputs, decode/audio/subtitle/source-coverage checks and actual OP/ED/action/quiet-scene review. Apply the same algorithm to all three available sources before claiming broad readiness. Tests protect contracts; sampled frames and ASR word checks do not establish editorial acceptance or complete speech accuracy.

Additional actual ASR evidence: source132.59–134.27 contains isolated «говорите!»/«Первая» during the OP; source179.01–181.77 contains «сигарета. Перекур с тобой за супермаркетом.» while the title is visible. The VERSION1 checkpoint in cancelled job960 explicitly protects U019/U020/U029/U030 as narrative exceptions. These words cannot establish a new episode event. Fumo1337.43–1347.35 explicitly asks to subscribe to uploader social channels; remaining speech discusses the dub and thanks viewers. Role separation has concrete evidence on these sources, but must preserve uncertainty on unrelated narrative voiceover.
