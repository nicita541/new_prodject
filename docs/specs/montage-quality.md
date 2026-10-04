# Montage quality specification

## Goal

Produce a chronological, condensed story that remains understandable and keeps the episode's important scenes, speech, actions, reactions, and atmosphere. Apply the user's balanced compression choice to the active library episode and the latest completed job selected for review. Persist the editorial policy so it can be changed later without inventing an additional UI control.

## Source of truth: confirmed user choices

- The primary reference episode is **«История о перекуре за супермаркетом»**. The user confirmed this after the project-library state was checked.
- Keep the story chronological and understandable. The user prefers balanced compression and explicitly wants that choice persisted for future changes.
- Remove long dwell that has no plot contribution, such as an aerial building flyover, and remove exact or uninformative repetition.
- Preserve important silent action, including the girl wrapped in ropes during the kidnapping. Silence and motion by themselves do not prove that a scene should be kept or removed.
- Preserve almost all short reactions and jokes for atmosphere, even when they contribute little direct plot information. Do not cut these beats merely to make the result faster.
- Remove the unwanted OP that remained in part 2 and the unwanted ED that remained in the final part.
- Keep plot that follows the apparent ending when it belongs to this episode. Remove a next-episode preview.
- Quality is the priority. The user set no duration, runtime, or DeepSeek spending constraint.

These statements are acceptance requirements. They are not model heuristics: scene labels and source evidence must establish whether a particular interval is an episode opening, this episode's plot after the apparent ending, or a next-episode preview.

## Original user answers

The following answers are preserved verbatim, including spelling, so later summaries or translation cannot reverse their meaning:

- Desired result: `Последовательный сокращённый сюжет серии: понятно, что произошло, без потери важных сцен.`
- Compression choice and persistence: `давай пока баланс, но это мы сохраним если что потом поменяем`
- Useful/useless scenes: `длиные паузы без важной части сюжета, типо сцена с пролетом дома, типо тишина а камера просто пролетает сдания с верху в низ и все, это бесполезная сцена, а с цена с тищиной +- но там обматываю девушку веревками чтоб похотить это важная, повторы не нужны`
- Reported defects: `там 1 проект с 1 серией, там и во 2 части опенинг есть и в конце часть эндинга есть , остальные были удалены нол там тоже есть ошибки`
- Post-ending story and constraints: `если после эндинга есть и это не что будет дальше а часть сюжета то надо оставить, ограничений нет, главное красота`
- Primary reference: `Да, «История о перекуре за супермаркетом».`
- Atmosphere: `Сохранять почти все реакции и шутки ради атмосферы.`

OP in part 2 and ED in the last part describe unwanted footage, not a requested placement rule. The verified primary/latest completed reference job is `928a9e13-a294-48f3-8231-09edd61bdf2b`; the gifted-girl job with prefix `013` is a separate regression reference.

## Evidence and limits

Keep current user reports, source-code diagnosis, historical output observations, and hypotheses distinct:

- The current request identifies defects in the active library and the latest completed job. The primary reference is confirmed above; inspect the current selected episode and latest completed job before using saved annotations or outputs as ground truth.
- Previous quality reports describe older jobs and manual review. They are useful regression evidence, but do not establish what a fresh run does now. In particular, an older manually excluded opening is not proof of automatic classification.
- The source diagnosis reports a reproducible overlapping-credit-cluster failure: a later cluster can overwrite a rescued event's excluded ranges and reset its selected ranges, restoring confirmed credit footage. The diagnosis report is tracked separately in `docs/qa/montage-quality-diagnosis.md` when available. This finding concerns credit clustering; do not infer that it explains every current defect.
- The existing suite passed 344 tests in the separate baseline run recorded in `docs/qa/montage-quality-baseline.md`. Passing that suite establishes technical baseline only, not editorial acceptance.
- Missing explicit production-sequence versioning in a cache key was identified as future fragility, but no current stale-cache reproduction was established; keep it a hypothesis unless reproduced.

## Acceptance criteria

The reviewed fresh output and its cached rerun must satisfy all of the following:

1. Remove confirmed pure OP from part 2 and confirmed pure ED from the final part. Preserve current-episode plot after the apparent ending and keep its last retained story beat chronologically last. There is no required montage-part placement or count for the opening or ending.
2. Confirmed pure opening/ending credits, promotional material, and next-episode preview are removed. Mixed or interleaved credit regions do not erase neighboring or overlapping story content.
3. Plot belonging to the current episode after an apparent ending remains. A next-episode preview is excluded based on evidence that it is a preview, not simply because it follows credits.
4. Complete recognized dialogue and the actions, causes, outcomes, and reactions that make retained scenes intelligible survive selection and part boundaries.
5. Long non-event dwell and exact or uninformative repetition are removed when the ground truth confirms no story or atmosphere value. Short reactions and jokes are retained by default when they carry atmosphere, even if their direct plot contribution is low.
6. Consequential silent action survives. Aerial scenery can be removed when it has no plot contribution. A rule based only on silence, stillness, motion, or adjacency cannot decide either case.
7. Parts play in chronological order, rendered video and subtitles remain synchronized, and the intended visual continuity is intact.
8. A fresh run and a cache-backed rerun use the same persisted policy and produce consistent editorial decisions. Cached answers remain valid only for matching evidence, policy, and model/profile identities.
9. Results for the confirmed primary episode and the latest completed job are reviewed independently. Evidence from another project or an older manual edit cannot satisfy either review.

## Evaluation record

Before implementation, the evaluation owner records for each labeled interval: project/episode selection, source in/out points, current rendered part/time, label (keep/cut/uncertain), reason, ground-truth evidence, whether it overlaps another classification, and expected post-fix behavior. The private media, API payloads, settings, and per-job files stay in ignored project data; keep review annotations in the tracked QA report without copying secrets or raw provider data.

Required contrasting examples include:

| Example | Expected judgment | Evidence needed |
| --- | --- | --- |
| Confirmed pure opening or ending credits / next-episode preview, including reported OP in part 2 and ED in the final part | Cut | Current frames, sequence context, and confirmation that it is not this episode's story |
| Opening interleaved with story, including a rescued event inside overlapping credit clusters | Remove only confirmed credit spans; preserve the rescued event | Before/current/after frames, selected ranges, exclusion ranges, and cluster ordering |
| Plot after the apparent ending that resolves this episode | Keep | Story continuity and current-episode resolution |
| Silent kidnapping action with the girl wrapped in ropes | Keep | Visible causal action and consequence |
| Brief humorous reaction or joke | Keep in almost all cases | Timing/context and atmosphere; low plot relevance alone is insufficient for removal |
| Long aerial building flyover without plot contribution | Cut | No story change across the interval and no later dependency |
| Exact or uninformative repeated view/exchange | Cut a redundant copy only | Identify an earlier retained witness and verify no new joke, reaction, or story beat |
| Motion or silence without enough context | Uncertain; preserve pending review | Current frames and surrounding context do not establish value |

## Implemented policy and remaining evaluation

`app/editorial.py` validates a per-job `editorial-settings.json` with schema version `1`, policy `balanced-atmosphere-v1`, and boolean flags `preserve_reactions`, `preserve_humor`, `remove_empty_holds`, and `remove_exact_repetition` (all default to `true`). Analysis atomically persists the default only when the file is absent; an existing incompatible profile fails validation. This adds no UI control or library-wide settings migration. Editing the accepted flags changes the job's editorial intent on reanalysis.

The complete profile participates in the derived story identity and story, closing, source-role, and pacing decision fingerprints. The derived identity also records production-sequence/source-role versions, credit context radius, provider image-page capability, and existing semantic model/stage identities. Compatible factual preparation and independently matching paid response caches remain reusable.

Credit clusters compose confirmed exclusions as a union against original input selections. Independent source-role proofs distinguish current-story dialogue/narration from uploader promotion, title narration, next-episode preview, and song/ASR artifacts. Exact supplied speech and visible markers are evidence; song/artifact removal additionally requires the unit to belong to a confirmed credit sequence. Mixed, protected-atmosphere, or uncertain units remain. Later dialogue rescue and planning subtract confirmed exclusions so they cannot resurrect nonstory footage. See [the architectural decision](../ai/decisions/0012-editorial-policy-and-source-roles.md).

The independent source review and focused checks are recorded in [the QA review](../qa/montage-quality-review.md). Post-change QA ran `tools/python/python.exe -m pytest -q`: 354 tests and 134 subtests passed in 20.26 s, with one existing Starlette/httpx warning; its focused gate passed 107 tests and 33 subtests in 1.06 s. Exact fresh/cache-backed run identities, rendered OP/ED removal, subtitle/audio synchronization, and editorial acceptance remain separate pending gates. Dense source-frame observations and technical tests do not prove the resulting montage passed them.
