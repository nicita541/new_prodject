# Montage quality baseline

Recorded 2026-10-04 in `F:\new_prodject`. This is a test and evaluation baseline; it is not acceptance of montage quality.

## Executed baseline

Command:

```powershell
tools/python/python.exe -m unittest discover -s tests -q
```

Result: `Ran 344 tests in 19.867s` — `OK`. One Starlette/httpx deprecation warning was emitted. The portable Python application config uses `F:\new_prodject\temp` and `F:\new_prodject\cache`; tests use the project temp directory. No model inference, download, remote API, or full-video analysis was run.

The README's recorded 280-test count is historical. `pytest.ini` sets `tests` as the test path and disables pytest's cache provider; the repository's current handoff also records 344 pytest tests, but that is not a command run for this baseline. The established Node command references `E:\nodejs\node.exe`, outside the project. There is no project-local Node runtime under `tools`, so the Node UI suite was not run under the repository's workspace-only runtime constraint.

## What current tests protect

Tests exercise useful deterministic contracts:

- `test_production_sequence.py` checks complete opening-sequence unit ranges, immediate outside witnesses, anchor-inside-sequence validation, a quiet narrative exception, and restoration when independent anchor confirmation fails. Its five synthetic units are each five seconds long.
- `test_production.py` checks credit/story mixtures, preserving later scenes, confirmed credit-only deletion, and conservative behavior on malformed or unavailable evidence.
- `test_closing.py` checks ending anchors, opening versus ending classification, recap filtering, protected dialogue, and silent consequences.
- `test_pacing.py` checks silent emotional consequences, evidence-backed scenery/repeat deletion, and that omitted material cannot witness another deletion.
- `test_analysis.py` and `test_planner.py` cover unit selection, dialogue restoration, chronological range composition, dependency preservation, and source-time validation.
- `test_media.py` and `test_subtitles.py` exercise synthetic FFmpeg exports, source audio, subtitle files/rendering, durations, and stream timing when portable FFmpeg is present. `test_output_review.py` checks sample timestamp selection, not semantic quality of a reviewed montage.

These tests mostly supply canned model answers and assert validation or deterministic downstream behavior. They do not establish that an actual model finds the complete opening/ending boundaries, distinguishes quiet story from decorative motion, or produces an editorially coherent montage on anime footage.

## Provider-path coverage gap

`app.production.clean_sequences` dispatches on `vision.supports_image_pages`. `DeepSeekVision` advertises this capability and uses `clean_whole_sequences`; local and hybrid vision objects do not, so they use the legacy continuation path. The `deepseek_plan` analysis provider also uses DeepSeek for story analysis. Existing tests exercise `clean_whole_sequences` and legacy continuation helpers separately, and provider construction separately, but do not run semantic fixtures through the dispatcher for both capability branches. A change to the selected worker/model/provider could therefore leave one production route unverified.

Add a small offline integration matrix around the real `clean_sequences` dispatch, with deterministic fake providers that record page order and return fixed decisions:

1. Page-capable provider: exercise one original opening cluster with an earlier credit page, interior anchor, immediate before/after story witnesses, and a quiet narrative unit. Assert the resulting source ranges and warnings, not only `sequence_decision` output.
2. Legacy provider: run the equivalent mixed credit/story case through the no-pages route and assert its final ranges and warning behavior.
3. Negative controls: missing/low-confidence anchor and malformed/uncertain decisions must preserve source ranges; a proposed narrative exception must survive; a proposed deletion must not be authorized by an omitted neighbor.
4. Reordering/cascade: use two adjacent candidate clusters and assert decisions use original input evidence and output ranges remain in source chronology with no overlap or accidental restoration of an already confirmed removal.

Use the same semantic cases with each provider capability rather than relying on provider class construction tests. Keep remote calls patched or cached; these tests must not spend API balance.

The dispatch regressions cover both routes: the legacy single-image route removes a confirmed credit unit while retaining adjacent story, and the page-capable route sends overlapping cluster decisions through planning while preserving both exclusions. The identity check covers `local`, `hybrid`, `deepseek`, and `deepseek_plan`, editorial-policy changes, and a sequence-version bump independent of the edge version. Added role and atmosphere checks exercise exclusions through speech rescue, JSON round-trip, cached role replay, and final planning; protect current-story speech, a silent action, and an almost-all-retained reaction; and verify that malformed partitions and unproven ASR/title/preview/song claims cannot authorize deletion. Separate checks cover closing/pacing protection for low-plot reaction beats and editorial settings that disable repeat or empty-hold removal.

Final deterministic validation after these changes:

```powershell
tools/python/python.exe -m pytest -q
```

Result: `354 passed, 134 subtests passed, 1 warning in 20.26s`. The warning is the existing Starlette/httpx `TestClient` deprecation. The narrower integration/domain run before the final role-schema check was `tools/python/python.exe -m pytest -q tests/test_source_roles.py tests/test_production_sequence.py tests/test_production.py tests/test_story.py tests/test_closing.py tests/test_pacing.py tests/test_analysis.py` → `107 passed, 33 subtests passed in 1.06s`; the added role-schema regression separately passed with `tools/python/python.exe -m pytest -q tests/test_source_roles.py` → `4 passed in 0.23s`.

## Confirmed overlapping-cluster regression

The montage implementation owner reported a deterministic synthetic reproduction, not independently run by this audit: events span 0–10, 10–20, and 20–30 seconds; the first and last events are original credit anchors; adjacent context expansion makes their clusters overlap. The first decision excludes 10–15 seconds, the second excludes 15–20 seconds, and the shared event's later result overwrites the first exclusion. Planner speech protection then reconstructs the event from its full window, restoring the already-confirmed 10–15-second credit interval. The resulting plan contains 0–15 and 20–30 seconds. Add a regression against the production sequence path and planner, asserting exclusions accumulate monotonically and later speech/plot guards do not resurrect confirmed credit intervals.

The regression is now implemented across both production dispatch branches and the planner, and the full deterministic suite passes as recorded above. Real-output validation is still pending: inspect a fresh primary-source render and a cache-backed rerun against the independently reviewed point evidence; report retained intervals, confirmed removals, chronology/overlap, export timing, audio sync, and subtitle alignment. Point evidence does not establish complete continuous OP/ED boundaries, so uncertain surrounding footage must remain unscored until separately reviewed.

## Cheap offline failure reproductions

Build compact, hand-constructed event/shot fixtures and drive them through production entry points with fixed provider responses. Include these failure shapes without embedding any series names or assumed timecodes:

- An opening anchor appears after the sequence has already begun; material before the anchor is still part of the same continuous production sequence.
- A short decorative motion segment is inside the opening while a quiet story beat directly precedes it.
- A late montage contains both credit material and a quiet payoff or protected question/answer.
- A suggested exception is actually an ASR/title artifact; the same candidate exception is alternatively a silent, visually evidenced story beat.
- Two adjacent clusters and a retained witness exercise ordering, boundaries, and non-cascading decisions.

For each case, assert final selected source intervals, excluded intervals, chronological order, non-overlap, and whether uncertainty/warnings preserve footage. These fixtures should reproduce the algorithmic failure reported by reviewers without encoding a fix as a timecode or anime-specific rule.

## Real-footage evaluation protocol

The agreed target is a coherent, chronologically ordered condensed plot with balanced compression. Remove long no-event pauses, building flyovers, and repeated material; retain plot-critical silent actions (for example, a rope or kidnapping action), current-story content after the ending credits, protected dialogue, and almost all reactions and jokes that add atmosphere even when their plot contribution is low. Tests should distinguish an empty building dwell from a reaction or humorous beat; low importance alone must not authorize deleting an emotional beat. Remove opening/ending production sequences and previews. Do not set a fixed compression ratio, output duration, or API spend cap. Examples clarify annotation categories only; they must not become anime-specific production rules.

Create a small, versioned set of source excerpts from the authorized anime sources. Do not prefill guessed timestamps or labels. Store each excerpt's source hash, frame rate, duration, and provenance so later runs use identical media.

Two reviewers should independently annotate interval boundaries and semantic labels while viewing enough surrounding context to judge continuity. Adjudicate disagreements before comparing any model output. The annotation schema should allow multiple intervals and uncertain/ambiguous labels; it should record reviewer rationale and whether speech/transcript evidence was available. Keep model outputs and reviewer annotations separate.

Suggested fixture shape (all values below are placeholders, not an existing annotation):

```json
{
  "schema_version": 1,
  "source": {
    "id": "fixture-id",
    "sha256": "",
    "fps": null,
    "duration_seconds": null
  },
  "annotations": [
    {
      "start_seconds": null,
      "end_seconds": null,
      "label": "opening | ending | preview | current_story | silent_action | reaction | humor | dialogue | no_event_pause | scenery | repeated_material | ambiguous",
      "reviewer_ids": [],
      "confidence": "high | medium | low",
      "rationale": ""
    }
  ],
  "candidate_output": {
    "provider": "",
    "model_id": "",
    "decision_version": "",
    "selected_source_intervals": []
  }
}
```

Measure opening/ending boundary error in seconds and interval IoU; story/reaction retention recall; deletion precision for intervals reviewers marked as removable; retained-context/dependency coverage; chronology and overlap violations; and dialogue completeness. Report per-source/per-category counts alongside aggregate values so a strong score on common easy intervals cannot hide a missed quiet reaction. Use a blinded side-by-side review of the final rendered parts for continuity, source audio sync, and subtitle alignment.

For the declared, annotated benchmark, use these acceptance checks: no confirmed pure opening/ending/promo/preview material remains outside a one-frame boundary tolerance; every interval marked mandatory plot or silent action remains; every reviewed reaction/humor beat remains except a trim explicitly bounded in the annotations; output intervals are chronological and non-overlapping; dialogue is not clipped; exports complete without audio/video desynchronization. Report counts and failures by source and category. These criteria apply to the reviewed benchmark, not as a universal quality guarantee.

Have the app worker label the annotated evidence and a separate independent review worker inspect the final montage. Preserve both records and adjudicate disagreements instead of folding the model's own confidence into ground truth.

For cheaper worker/model comparisons, freeze the fixture set, provider route, prompts/decision version, decoding settings, and cached source assets. Run the same cases with each candidate worker, record semantic metrics, latency, input/output tokens or provider-reported usage, and any failure/fallback. Reuse compatible cached answers where that tests pipeline stability; do not treat cache replay as evidence that the alternate model would make the same decisions.

These benchmark criteria apply only to the annotated cases; no universal quality guarantee is asserted. Passing unit tests, a successful export, and a low-cost run are separate facts from acceptable editorial quality.
