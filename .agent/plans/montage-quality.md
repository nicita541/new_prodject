# Goal

Make the condensed output understandable and pleasant while preserving the confirmed story, dialogue, consequential silent action, and brief humorous/reaction beats. Remove only evidenced non-event dwell, redundant repetition, confirmed credits/promotional material, and next-episode preview. Apply the user's confirmed chronological, balanced profile to the primary reference episode and independently to the latest completed job. Persist the profile for later changes.

# Current state

- `docs/specs/montage-quality.md` records confirmed user choices, evaluation examples, acceptance criteria, and questions that require repository evidence rather than invented requirements.
- The user confirmed «История о перекуре за супермаркетом» as the primary reference; its latest completed job is the main QA target. «Забота об одарённой девушке» is a separate cross-source regression. The current library has two unarchived projects despite the user's description of one active project/episode; preserve this state without archiving or restoring either project.
- Existing architecture separates analysis, story condensation, closing/sequence classification, pacing, planning, and rendering. The user-facing pipeline is local-first with explicit optional remote-analysis modes; preserve existing project/job ownership, saved choices, and accounting/cache safeguards.
- The overlapping-credit-cluster defect is reproduced and corrected by composing exclusions once from immutable input selections. Independent source review also reproduced and verified corrections for disabled policy flags and later closing/pacing passes deleting protected atmosphere. See `docs/qa/montage-quality-review.md` for the independently executed checks and their limits.
- `app/editorial.py` persists the versioned balanced profile in each job's `editorial-settings.json`; profile and semantic stage identities participate in derived/decision caches. `app/source_roles.py` independently verifies nonstory roles before global selection. See `docs/ai/decisions/0012-editorial-policy-and-source-roles.md` for precedence and compatibility.
- A separate baseline run passed 344 tests; see `docs/qa/montage-quality-baseline.md` when saved. That does not establish editorial quality.
- Post-change QA ran `tools/python/python.exe -m pytest -q`: 354 tests and 134 subtests passed in 20.26 s, with one existing Starlette/httpx warning. Its focused gate passed 107 tests and 33 subtests in 1.06 s. These do not establish rendered/editorial acceptance.
- The user has set no output-duration, runtime, or API spending constraint. Keep the established provider mode/settings and safeguards; do not add an arbitrary cap.

# Constraints

- Keep all task files and artifacts in `F:\new_prodject`. Preserve source media, jobs, settings, model data, prior outputs, and user annotations.
- Keep private media and data/settings, credentials, API payloads, raw provider output, models, external tools, caches, and generated exports out of Git. Add only explicitly reviewed source, tests, docs, and reports.
- Keep answers in the specification as the editorial source of truth. Do not generalize the examples into title/object/timecode shortcuts.
- Preserve the existing episode/job identity and recovery/accounting behavior. Any policy setting must be versioned in the appropriate decision/cache fingerprints and must not silently migrate incompatible saved choices.
- Parent agent coordinates and integrates. The implementation worker owns only the agreed analysis/story/sequence/pacing modules; the QA worker owns its assigned tests and baseline report; the diagnosis worker owns its diagnostic report. No parallel edits to overlapping files.
- Implementation and quality sign-off remain separate gates. Automated tests, successful encoding, or one historical output do not alone establish editorial acceptance.

# Implementation

1. **Freeze the review baseline.** Use the confirmed supermarket episode/latest completed job as primary, and keep the gifted-girl job as a distinct regression. Record relevant intervals and classifications in the private QA workflow. Distinguish observed fresh-run behavior from historical exports and manual annotations. Preserve both unarchived library projects.
2. **Reproduce and isolate selection defects.** Use source-backed intervals to exercise overlapping credit clusters, rescue/selection range mutation, pure versus interleaved credits, the reported OP in part 2 and ED in the final part, and post-ending episode plot versus preview. Record uncertainty without turning it into deletion.
3. **Implement the smallest safe correction.** Fix range/cluster composition so a later cluster cannot destroy previously rescued story ranges. Preserve speech, cause/action/outcome, and short reactions/jokes. Keep title/preview ownership in the dedicated sequence logic and preserve the user's current provider mode and saved decisions where compatible.
4. **Persist the editorial policy.** Store chronological story, balanced compression, atmosphere-protecting brief reactions, evidence-bound repetition/dwell removal, and version identity through the existing settings/decision path. Avoid new UI unless code evidence shows users need a visible control to change this saved choice.
5. **Protect behavior with varied tests.** Cover range/cluster overlap and ordering; pure/interleaved titles and story; post-credit plot versus next-episode preview; silent consequential action; brief humor/reaction; scenery and non-event dwell; repetition witnesses; dialogue completeness; removal of reported OP/ED; policy save/load/change; and cache invalidation/reuse. Use offline deterministic tests for domain behavior, integration tests for pipeline state and output structure, and real-source review for model judgments. Never use a test label as proof that a real model classified a scene correctly.
6. **Review end-to-end outputs.** Generate a fresh result for the confirmed reference under the existing selected mode, then repeat from compatible cached decisions. Compare source intervals, selected/excluded ranges, parts, subtitles, and files. Review the latest completed job separately where it represents a different project/episode. Update the QA report with concrete evidence and remaining uncertain intervals.
7. **Sync durable docs and handoff.** Update the specification/context only for confirmed durable behavior. Keep historical notes intact. Report the exact tests and manual evidence run, limitations, and the state of each acceptance criterion.

# Validation

- Run the established portable full-suite command `tools/python/python.exe -m unittest discover -s tests -q`; scoped suites may use the same runtime with explicit test modules. Record pytest only when actually executed. Do not install or download dependencies. The separate baseline reports 344 tests; the independent review ran 116 focused tests. The Node UI suite is not verified under the workspace-only runtime constraint; no project-local Node runtime was available in that baseline.
- Add meaningful deterministic tests across the cases in Implementation milestone 5, including an overlapping credit-cluster regression with a rescued selected interval.
- Verify persisted policy round-trip, behavior change after an explicit profile change, and matching/mismatching cache fingerprints.
- For the real reference episode, verify OP removal from part 2, ED removal from the final part, the last retained current-episode story beat, all labeled credit/preview/post-ending cases, short atmosphere beats, silent action, scenery, repetition, dialogue handles, subtitles, and continuity. There is no opening/ending placement or part-count requirement.
- Compare a fresh run with a cache-backed rerun. Confirm decisions and rendered structure remain consistent under the same policy/profile; record any paid-call/cache behavior actually observed.
- Have the user or coordinator sign off the QA table criterion by criterion. Do not mark editorial acceptance complete solely because tests pass or files decode.

# Risks and rollback

Overly broad credit spans can delete interleaved story content; overly conservative classification can retain clutter. False repetition witnesses can remove a joke or meaningful reaction. Cache profile omissions can reuse stale decisions. Reduce these risks with immutable selected/excluded ranges, explicit evidence links, independently labeled examples, and policy/model/source fingerprints. Preserve current media, job data, choices, and exports; rollback by reverting the isolated source/test/doc commits and rerunning from preserved inputs. Never remove a user's current job or paid-account ledger as part of rollback.

# Progress

- [x] Gather user answers and write the source-of-truth specification.
- [x] Establish a safe local Git baseline and working branch.
- [x] Confirm the primary episode/latest completed job and separate cross-source regression; preserve unarchived library state.
- [x] Reproduce and fix overlap/range defect with isolated regression coverage.
- [x] Persist the editorial policy and validate cache identity with focused deterministic checks.
- [x] Complete finite independent source review; reproduce and recheck policy/atmosphere corrections (116 focused tests passed).
- [x] Complete QA's post-change full-suite and deterministic regression gate: 354 tests + 134 subtests; focused 107 + 33 subtests.
- [ ] Review fresh and cache-backed real outputs against all acceptance criteria.
- [x] Save independent review, dense source-frame observations, policy architecture, and remaining uncertainty; final output acceptance remains pending.
