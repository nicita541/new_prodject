# KADR Studio: standalone Shorts architecture

## Goal

Implement the architectural plan approved in this chat: survey the episode, find independent short stories, deeply inspect only useful candidates and prerequisites, compile each clip deterministically, and publish verified outputs with resumable execution. Preserve the complete scope until real-video editorial, cost, recovery and compatibility acceptance is demonstrated.

Defaults accepted by the user: up to three standalone stories, 45–90 s preferred and 120 s ceiling; quality takes precedence over count. Local media/ASR/initial vision plus cloud story understanding is the primary route; local-only remains supported. Return accepted clips and separately labelled technically safe drafts when semantic uncertainty remains. No comparison to the rejected previous audit. An independent subagent through the installed Antigravity console is mandatory.

## Current state

Initial inspected revision: `c4bb1b7`, `codex/dramatic-montage`. Existing dirty files belong to preceding work: `.agent/plans/confirmed-fragments.md`, `app/confirmed_selection.py`, `app/pipeline.py`, `docs/ai/decisions/0053-confirmed-fragment-working-selection.md`, `tests/test_confirmed_selection.py`. Preserve their changes; do not reset/stash them or silently claim ownership.

Useful foundations: FastAPI, isolated worker and Windows Job Object, atomic JSON, StageJournal/AcceptedReplies with source/input provenance, source-time speech/action guards, deterministic plan, source timeline and bounded parallel FFmpeg exports.

Current product mismatch: episode-wide retention followed by partitioning, episode-level unresolved gates and continuity, overlapping selection/story/dialogue passes. Reproduced validation omission: removing [3.00,3.04) from [0,8) passes existing plan and final quality checks. Recovery lacks live-worker heartbeat and FFmpeg stall deadlines; malformed job.json is not isolated during startup.

Historical job `cef8da9c-4a98-4284-b2e8-4ccd0870562d`: 18 saved runs, 2,582 responses with usage, 8,387,178 tokens, no outputs. These are cumulative historical figures, not one current cold run. Cloud input dominates usage; errors/retries alone do not explain it.

## Constraints

- Keep installs, caches, temporary files, review packets, logs and outputs under F:/new_prodject. Use portable Python/Node; no global installs.
- Preserve sources, private settings, accepted raw replies, completed artifacts and producing-provider provenance. Never log credentials.
- Do not add services, queues, databases, embedding models or new dependencies without demonstrated need.
- Keep one coordinator for checkpoint/status publication; GPU models execute sequentially on 8 GB VRAM.
- Read legacy jobs through adapters. Do not rewrite historical signatures as new signatures or weaken technical gates to manufacture success.
- Treat source evidence as immutable; candidate plans own selection. Within a clip, preserve source chronology in v1. Independent clips may overlap and be ranked separately.
- No paid inference through tests; bounded real model experiments must be explicitly recorded as such. The user authorizes implementation and an Antigravity review subagent, but report publishing/messaging third parties is outside scope.

## Implementation

0. Preserve baseline and add one attempt/request/stage/candidate identity across diagnostics and token records. Distinguish transport attempts, cache reuse and incomplete requests. Prepare versioned corpus/measurement contracts.
1. Fix introduced one/two-frame edit islands and gaps without rejecting natural source cuts; make heuristic eyecatch advisory; isolate malformed job records; detect owned-worker/render hangs; validate only required models and check caches before opening sessions.
2. Evolve StageJournal into source evidence, candidate/plan and artifact manifests. Keep source immutable. Add idempotent submissions and atomic output revisions, legacy adapters, per-artifact ready/draft/error state. Maintain prior ready revisions after new failures.
3. Implement standalone-story planning using existing qualified evidence first. Identify premise/development/outcome and prerequisites; apply continuity/gates per candidate; rank independently; emit fewer clips and safe drafts rather than reintroducing the episode.
4. Replace mandatory overlapping episode-wide semantic passes with coarse survey, compact episode map, candidate-specific deep analysis and a finite journal of useful unanswered questions. Batch shared evidence, reuse negative results and apply one source-grounded semantic record. Keep local/cloud adapters on common contracts.
   - The real trials invalidate using the legacy micro-unit qualification chain as the final standalone owner. Implement a versioned whole-candidate route: complete utterance/shot source catalog → source-backed edit proposal → independent review of the actual proposed cut timeline with original context. The reviewer must supply grounded opening/development/ending proofs, complete retained dialogue coverage and per-cut boundary checks. Its explicit unresolved/context/quality verdict owns eligibility; do not manufacture .9 legacy unit confidence or migrate old answers into this new contract. Keep old selective analyses readable. Reuse technical plan validation, source frames, useful-question journal, final framing and immutable publication. Support ordered multiple cut groups, not only continuous extracts. Treat context-capacity limits as unresolved candidate outcomes, and provider failures as technical failures. Verify actual real candidate stories before default rollout.
5. Compile PTS/audio-safe boundaries and adaptive pacing; preserve meaningful nonverbal audio/actions. Frame only final selected material. Fully decode and validate every published output against its immutable plan.
6. Unify finishing cancellation/recovery with managed execution, persist operation parameters, and reuse immutable ancestor artifacts rather than copying large files. Protect referenced ancestors from cleanup.
7. Run task-appropriate product and component comparisons, blind editorial evaluation and fault injection. Enable the new pipeline only after acceptance; remove old-path redundant owners/copy-restore mechanisms after reference and compatibility checks. Update ADR and stable architecture documentation.

Each milestone must leave a coherent runnable version. Work may progress across goal turns; finishing milestone 1 or passing synthetic tests does not achieve the full goal.

### Contracts

- SourceEvidence: source SHA, selected streams, actual PTS/time bases, ASR, shots, frame/audio facts and provenance.
- EpisodeMap: source-linked events, story hypotheses and dependencies; uncertainty is explicit and distinct from technical failure.
- ClipCandidate/ClipPlan: standalone purpose, prerequisites, cuts, source/output time mapping, verdict and reasons.
- ArtifactManifest: schema/version, exact input identities, producer, output SHA and commit completeness.
- JobOutcome: accepted outputs, drafts, declined candidates and technical failures. Drafts never masquerade as ready outputs.
- New objective setting: standalone_shorts; default requested count 3, preferred 45–90 s, max 120 s. Existing jobs retain pipeline version.
- New operation_id for creation/export: exact same payload reuses operation; conflicting payload fails; crash recovery completes the same intended operation.

### Analysis budget

New inference must identify an unresolved question, affected candidate/cut, new evidence, possible plan changes and estimated cost. Reject identical question/evidence repeats and questions unable to change any result. Prioritize feasibility blockers, then candidate ranking, then optional polish. Calibrate estimates by purpose/model/text/image workload; do not equate model confidence to measured probability or invent a universal request cap. No account-balance ledger is reintroduced.

## Validation

Discover and use repository commands; portable `tools/python/python.exe -B -m pytest -q` and native Studio scripts. Set TEMP/TMP/TMPDIR/log paths inside the workspace and disable bytecode for checks. Do not run BAT report publishers.

- Regression: 40 ms introduced gap, tiny retained islands, native fast shots, exclusions, word/action boundaries, VFR/audio tails, quiet mid-episode story.
- Product: unresolved irrelevant footage does not block accepted independent clips; independent chronology/ranking; complete question/answer; standalone opening/development/ending; fewer outputs plus distinct draft.
- Durability: malformed job among healthy jobs; crash at artifact/manifest/publication steps; lost submission response; hung FFmpeg; OOM/provider/network failures; cancellation and restart; output hash mismatch; source/settings scoped invalidation.
- Warm run: no new completed semantic requests; style changes do not repeat ASR/story; planning changes reuse source facts; accepted provider provenance survives switches.
- Corpus: both local full episodes plus four diverse sources when supplied/available; 12 short cases; held-out editorial cases. Do not claim missing sources or reviews are completed.
- Measure cold/warm attempt separately: time to first output, wall, reported tokens/requests by purpose, deep source coverage, frames/decodes, CPU/GPU/RAM/VRAM/disk, accepted clips and severe defects per output minute. Compare identical component workloads separately from different product output scope.
- Editorial: watch clip before source; score interest, standalone comprehension, causality, pacing, audio/action completeness, ending and framing. Proposed release threshold: >=4/5 for standalone comprehension/causality/ending and no critical distortion; preferably two independent reviewers. Model confidence is not editorial acceptance.
- Antigravity: bounded code-review packet, read-only/restricted tools, exact evidence and raw response under temp, coordinator validates findings with actual regressions.

## Risks and rollback

Keep old pipeline version readable and selectable until acceptance. New execution uses new qualified manifests; never overwrite original media or raw replies. Preserve the initial dirty diff under temp. Revert only changes owned by this plan. If a new revision fails, previous committed output remains available. Cache incompatibility must be explicit and scoped, not hidden by frozen hashes. Coarse survey must be checked for silent-story recall; correct missing coverage rather than approving arbitrary selections.

## Progress

- [x] Architectural investigation and user decisions completed in chat.
- [x] Implementation and mandatory Antigravity subagent authorized; execution mode enabled.
- [ ] Baseline snapshot and unified measurements.
  - [x] Original dirty diff/source revision preserved under workspace temp; job/attempt/stage/candidate and transport identities linked to diagnostics/token records.
  - [x] Versioned corpus/measurement/editorial protocol: docs/quality/standalone-acceptance.md.
  - [ ] Six real-source corpus registration and real cold/warm measurements.
- [ ] Narrow correctness/reliability fixes.
  - [x] Introduced micro-edit validation, advisory eyecatch, corrupt-job isolation, worker heartbeat, FFmpeg deadlines and full decode receipts.
  - [x] Provider/layout-aware model requirements and lazy ordinary local model acquisition.
- [ ] Immutable evidence/manifests and compatibility.
  - [x] Immutable StageJournal/source evidence with legacy adapter; submission receipts and restart recovery; independent immutable output revisions.
  - [ ] Managed finishing lineage and removal of copy/restore paths.
    - [x] Published caption corrections follow source candidate/cuts/words across ranks; stale saves reject, queued renders snapshot matching corrections. Managed processes, operation recovery and same-job media references are implemented. Cross-job immutable render/clean references and validated source-owned ASR PCM now avoid large snapshot media copying (ADR0057/0065).
- [ ] Standalone candidate planning and explicit drafts.
  - [x] Pure source-backed compiler, candidate-specific gates, ranking and opt-in pipeline/API integration; explicit draft proposals.
  - [x] Studio objective selector, preserved custom settings, explicit outcomes, sparse ranked-file mapping and submission UUID retry protection.
  - [ ] Rendered safe drafts and real-video editorial acceptance.
    - [x] Continuous-source review rendering, separate immutable storage/API/UI and preservation of prior ready publications; three real videos fully decoded. Editorial acceptance remains pending.
- [ ] Coarse-to-fine source analysis and useful-question budgeting.
  - [x] Whole-source sparse survey, complete-ASR bounded map chapters, hypothesis-only contract, selective native qualification and final-candidate framing integrated.
  - [x] New source-only standalone_source_v2 separates survey from edit preferences. Whole-candidate proposal/native review/pure compiler replaces mandatory micro-unit qualification for new standalone jobs; legacy selective readers remain.
  - [x] Batch original PTS/frame extraction across physical owners without changing their source proof; exact JPEG/PTS parity verified on all three real candidate contexts.
  - [x] Discovery question reservations, positive/negative reuse, no automatic repeat after unknown dispatch, cross-instance exclusive reservation.
  - [ ] Real recall/cost calibration, priorities across native questions and precise subscene deep scopes. Explicit new-job StageJournal/reply/question ancestry is implemented and mechanism-tested; immutable render/clean ancestry is also implemented (ADR0057).
- [ ] Adaptive audio/action boundaries and final framing/export QA.
  - [x] Measured selected-track edge PCM with source PTS, relative valleys, immutable reuse, omitted-word/exclusion barriers and pre-review compilation. Synthetic/actual-stream tests and authorized120s signal calibration completed (ADR0058).
  - [x] Source-shot/cut/motion-targeted candidate observations and genuinely new requested-unit enrichment; formerly172-image source packet now143 owned images, ordinary source+blind checks reached (ADR0059).
  - [ ] Adaptive visual-action observation, listening acceptance, VFR/full-source boundary coverage and corpus editorial acceptance.
- [ ] Finishing recovery and artifact ancestry.
  - [x] Managed immutable-command export/preview, durable queue, explicit resume/cancel, API/browser retry identity and same-job verified media references. Actual generated FFmpeg/process/HTTP interruption/restart flow verified.
  - [x] Rendered-artifact references across analysis jobs, verified read-only clean reuse, no incremental clean/output/render copying, and ancestor lifetime protection.
  - [x] Source-owned ASR PCM reuse and exclusion of root/perception WAV from snapshots; small checkpoint metadata copying remains intentionally (ADR0065).
- [ ] Antigravity independent review, actual-model trials and editorial acceptance.
  - [x] Actual Antigravity console child completed the bounded caption-ownership review. This does not certify the full architecture.
- [ ] Rollout, redundant-path removal and documentation.

## Verification log

Prior read-only investigation ran 69 unittest tests and a separate 91 pytest tests with 13 subtests; these are historical checks, not validation of implementation changes. Real-video new-architecture acceptance remains pending.

2026-10-16 implementation: telemetry/eyecatch focused suite 66 tests +27 subtests passed; edit-integrity/planner agent suite126 passed; managed-worker suite72 +19 subtests passed; FFmpeg/media agent suite41 +2 subtests passed (one stale test then corrected). Pure standalone compiler13 new tests and129 nearby tests passed. Immutable publication18 tests passed; lazy/provider lifecycle23 passed. Real run_job standalone orchestration/API + objective persistence10 tests passed with explicit authored media boundary stubs, no inference or real encoding.

Combined root suite (API, jobs/operations, evidence/publication, analysis/provider/lifecycle, pure standalone, quality pipeline and semantic identity):205 passed +47 subtests, one failure because expected component-name inventory lacked the newly added standalone component. That inventory was updated; combined rerun pending. Earlier stale global-review fixtures assumed original IDs rather than existing compact wire IDs and repeated identical rejected requests; fixtures were aligned to the unchanged HEAD production contracts.

Antigravity code-export permission and its service-state directory under C:/Users/Никита/.gemini/antigravity-cli are explicitly authorized. Two initial native CLI attempts returned empty zero-token SUCCESS after timeout; neither is accepted as review. A real console invoke_subagent subsequently dispatched kadr-code-review, ID e8e84e32-004b-4f99-84a6-d0cf719028d6, from conversation40559485-9ced-4e90-a695-d749fa63289c. It did not return a final review. One bounded attempt to collect the existing result also timed out with an empty response. No completed independent findings are claimed; do not loop/replay the question blindly. Packets/logs remain under temp/antigravity-standalone-review. No credentials/media/transcripts were supplied. User prohibited Astra; new internal subagents explicitly used gpt-6.1-sol.

Latest combined implementation validation:488 passed +123 subtests (one existing Starlette warning); Studio lint, both bridge/DOM smoke scripts and production build passed. Review caught missing production standalone scope routing and telemetry purpose allowlist; both fixed and tested with actual registry lookups. Dense survey batches use real token counts with output/template/image reservation. Ordinary lazy sessions support diagnostic contextmanager factories; recorder thinking changes reach the underlying model.

Genuine local trial now running with app source frozen: temp/standalone-local-trial-4b02b5b873064bcc98fb20e1b313503a, source excerpt120s starting300s, local provider/cinema/standalone objective, 1800s cooperative benchmark deadline; cloud HTTP is programmatically forbidden. Exec session70873; metadata temp/active-standalone-local-trial.json. Source/code/resource/raw-request evidence stays isolated. Do not edit app/semantic code while this run is active: the observer invalidates measurements after code changes. At the first observed sample ASR completed and real4B semantic-boundary requests were running; no accepted export/real editorial success is claimed yet.


2026-10-16 real local trial completed: 1741.563s for 120.037s of source, 112 requests, 383240 reported local tokens. Code identity remained stable. Outcome needs_review: accepted0, draft proposals3, declined8, technical_failures0; no exported video. Benchmark acceptance is failed, not a provider/encoding exception. Breakdown: semantic_boundary24, episode_survey3, episode_map1, selective_native59, choose_units25. This contradicts cost/product acceptance: discovery is cheap but native scene qualification still dominates and no final candidate passes. Next analysis change must remove redundant pre-discovery boundary inference and overlapping native selection/adjudication work without bypassing source/causality proof. Do not start another full cold repeat before addressing this evidence. Resource sampling covers the whole system and included brief mechanism tests, so it is not an isolated hardware performance comparison.

A further Antigravity console dispatch used subagent2e84b151-2ea2-44ff-bed0-16e5f2de53a1 from parent8fda564d-abc3-451f-b126-2a18b88dd1e9. It returned waiting text only, without final findings. No completed independent review is claimed; stop blind review retries. Packet: temp/antigravity-reservation-review.

Prepared an isolated checkpoint ancestry implementation while the trial source was frozen; prototype72 tests+20 subtests passed. Now integrated explicit source/owner-bound ancestor references, readonly StageJournal/accepted-reply/question reuse, retained unknown-dispatch reservations, and ancestor deletion/prune guards (including reserved submissions before reference commit). Legacy copy adapters remain; large render ancestry and managed finishing are not yet implemented. Finishing now selects the committed publication plan after a failed newer attempt; caption revision binding remains pending. Integrated verification running, not yet claimed passed.


Integrated ancestry/finishing validation:177 passed+49 subtests; analysis failure/publication API regression checks:81 passed+14 subtests. Early standalone technical-region routing and survey/native integration:63 passed+12 subtests before the final owner-kind/diagnostic wording refinements. The new route no longer invokes scene_checkpoint/boundary VLM before discovery and does not claim technical regions are semantic scenes. Physical source coverage and word preservation are checked; native source/story/dialogue/quality gates remain. Final combined checks pending.

Posthoc inspection of the completed real trial found6 invalid model/source contracts inside native unresolved audits, including malformed/truncated responses. The original technical_failures0 was a reporting bug, now fixed for new runs; original trial files were not rewritten. Detailed native response-schema/fanout redesign, rendered drafts and new real acceptance remain required.


Final combined owner checks:550 passed+128 subtests in96.11s, one existing Starlette deprecation warning. This verifies mechanisms/compatibility, not real-model quality. Subsequent cleanup/provenance checks:103 passed+36 subtests in25.85s; git diff --check passed. No new cold inference was launched after the failed acceptance run.

Next inference work, before another complete cold comparison: replace duplicated native keep/drop/action lists with one explicit per-unit decision record plus grounded kind/frame/quote proof; derive redundant lists mechanically from those native decisions, never invent or repair semantic labels. Preserve legacy accepted records through a versioned adapter and all existing source validators. Evaluate removing the redundant story-refinement/choose_units pass only when the source-grounded final qualification already supplies the same contract and structural/causal gates remain. Current real failures include missing keep/drop coverage, action-kind contradictions, causal links to dropped units, confidence-only rejection and output truncation. Preserve exact failure/retry provenance and avoid blind repeated requests. Rendered safe drafts remain a product requirement, not satisfied by three plan proposals.


Standalone native qualification now uses unit_decisions_v1: one explicit decision per unit and the same grounded kind/frame/quote validator, mechanically projecting redundant lists. The duplicated story_refinement/choose_units pass is removed from this objective only. Legacy adjudication remains the default for old routes. Native decision requests now reserve exact question/evidence/model identities before dispatch and retain known responses; unknown dispatches do not generate a correction request. Contract/native/provenance regression:127 passed+66 subtests; final small schema/counter checks12 passed. Remote observer now supports explicit deepseek_plan and counts real transport starts with model aliases, retries and incomplete-log indication.

User explicitly permitted paid DeepSeek calls. The first attempted controlled120s DeepSeek run was rejected before CreateProcess by automatic approval review, which requires explicit consent to transmit ASR and sampled frames. No paid request was dispatched. A concise asynchronous consent question is pending; do not bypass the rejection or start the dependent run until answered. Existing DeepSeek configuration and cinema/4B readiness were verified without exposing settings. Unaffected implementation work continues; no goal-blocked status is justified. Prepared runner temp/run-paid-standalone-trial.py and stdout target temp/standalone-deepseek-trial-console.log. No active paid experiment exists yet; app source need not remain frozen.

User subsequently explicitly authorized transmitting the120s excerpt's ASR and selected frames to DeepSeek. The previously rejected launch was retried with this new authorization and is now running: temp/standalone-deepseek-trial-17f8eaf7648b40fe8b2f28a8a5671cff, exec session22133. App/semantic source is frozen until this experiment ends. Different providers prevent an equivalent-workload speed claim against the prior local trial.

Safe-draft mechanism checks:115 passed+50 subtests; subsequent prior-publication regression and draft suite13 passed. Studio lint, bridge/DOM smoke and production build passed. Real draft-only run temp/safe-draft-media-trial-df1caaa60438466fa07160d50c6bc78a rendered3 videos (5.88s,44.62s,17s) in8.77s with0 model requests,0 failures and unchanged source hash. Actual backend rendering/full decoding was used, and one midpoint frame was visually inspected for full picture/subtitles. No listening or editorial acceptance is claimed. git diff --check passed.

Controlled DeepSeek trial has now ended:560.05s,28 local+55 remote transport attempts,83662 local+219469 DeepSeek reported tokens; code stable and transport counts complete. Outcome needs_review,0 ready clips,3 actually rendered continuous-source drafts (29.78/29.94/30.0s),5 declines,0 technical failures. All50 native decisions passed validation on5 owners and declared resolved, but no view met the existing confidence policy (minimums0.55–0.85), so structural story checks did not run. Do not infer safe ready stories or loosen thresholds merely to force success. Cold results preserved under job-120s/benchmark/fresh. Same-code warm run8.51s with0 new transport requests; cumulative83 is historical, not warm activity. App source unfrozen after both runs completed.

Caption ownership implementation: caption_state uses job/source/candidate/cuts/original-words identity independent of public rank/focus/layout. Published API saves require target echo and preflight under manager mutex; bound files preserve edits after re-ranking, legacy unbound files are not adopted. Queued finishing snapshots use matching state. Browser invalidates plan/caption caches together, preserves old unsaved words separately in the current window, and permits the committed publication of a failed job in finishing. Initial compatibility failure for a legacy helper without plan was fixed; subsequent53 tests+5 subtests passed, including publication/draft/finishing suites. Studio lint, DOM/bridge smoke and build passed; an additional target-echo smoke assertion is pending its final rerun.

New bounded Antigravity review targets only caption_state and the save-target helper. First launch failed before inference with empty prompt; corrected argv launch reached invoke_subagent but returned review_incomplete. Coordinator inheritCustomizations=false hid the existing custom reviewer definition; changed to true and one bounded retry is active (exec1094). No completed external review is claimed until final findings arrive. Prior broad packets remain unaccepted as completed reviews.

That bounded retry completed in173.69s: actual console subagent cae625b6-7ccc-4415-808a-52ab6c43b878 sent its report and finished; coordinator returned findings:[] and the same child ID. Child final public response independently confirms completion/report delivery. Packet/result: temp/antigravity-caption-review-fb1e4e05e09042a1877e79150ba29d28/review-result.json. This accepts only the narrow caption-ownership review, not the whole architecture. Parent init enumerates all global tools despite persona declarations; actual parent trace used invoke_subagent/wait/finish and no file/command/browser operations. Do not claim the CLI's allowlist enforcement is certified. Final caption target-echo and publication cache invalidation Studio smoke rerun passed. No active trial or external review remains.

Final UI flow inspection found two remaining completed-status guards in Apply/Preview despite the editor itself allowing a committed publication after a failed attempt. Both now use reviewable(job), and an actual DOM flow opens the failed job's published editor, applies finishing through the API adapter, requests preview and verifies that the failed analysis status stays unchanged. This regression and lint passed. Next source-quality work must inspect grounded low-confidence decisions and candidate coverage before changing qualification policy; no automatic confidence inflation, blind paid repeat or manufactured ready acceptance. Managed finishing process/command recovery, adaptive boundaries and corpus/editorial rollout remain unfinished.

Source evidence inspection changed the next action. Three real native storyboards show that format-valid decisions can still have wrong action ownership: the29.78–32.12s view describes an arm movement shown in frame6 while the purported action unit cites only frames4/5, before that movement. Its low confidence is not the only issue. Discovery also cut the27.86–30.24s utterance at29.78s merely because that is a word edge near the30s technical window. Implement complete-ASR-utterance discovery owners (word crossings still protected), with explicit long-indivisible-owner diagnostics. Strengthen native action proof to require distinct ordered owned before/after frames and observed states in a versioned contract; do not fabricate temporal proof from old one-frame records. Keep legacy contracts readable and unchanged. Verify schema/native/warm/unknown-dispatch behavior and inspect actual cached source evidence before another paid full repeat.

Implemented utterance-safe discovery v2 and unit_decisions_v2 temporal action proof; source selection and story-unit projection independently recheck persisted owned frame/time pairs. Historical v1 helpers remain explicit and unchanged; v2 cannot reuse a one-frame legacy action as temporal proof. Combined source/selection/story/native/identity checks189 passed+106 subtests. Actual source dry validation finds3 old boundaries inside complete utterances and0 new ones, with full coverage and no inference (temp/native-source-boundary-validation.json).

First targeted real temporal trial used an explicitly enabled low-reasoning DeepSeek mode, not the ordinary production factory: temp/native-temporal-trial-a6f752bf6bc34359b22ca3bd950237ef. Three cases used1/4/4 transport attempts, warm0 each;2 contracts validated and1 failed. Code/source stable. Empty length-exhausted generations exposed nested correction fanout (adapter format retry followed by another source-adjudication retry). Fixed: rejected finish_reason=length is terminal for identical parameters; ResponseContractError is not re-corrected by source adjudication and truncation is reported separately. Related111 tests+59 subtests passed.

Ordinary factory temporal test then completed: temp/native-temporal-production-trial-afc2ff09010b4b6c8382dbd27691b6b1. Three real bounded cases each validated in one remote call (6.41/6.08/4.75s), with0 warm requests,0 contract failures, stable code and unchanged source. All remained unresolved under the unchanged confidence policy (.70/.85/.85 selection). This validates the production wire/ownership mechanism only. It is not whole-story or editorial acceptance and does not establish that all described movements are true. The first reasoning-enabled test is not an equivalent-cost production comparison. App source is unfrozen; no inference remains active.

Remaining source-quality design issue: whole technical-owner confidence still vetoes all its independently grounded units, and dense deep views are often only1–3s. Before another full paid repeat, evaluate source/candidate-scoped semantic qualification with complete utterance/action context and an explicit uncertainty policy; avoid merely adding proofs or raising self-reported confidence until the old episode-wide machinery passes. Preserve raw answers and downstream source/closure/audio checks. Keep opt-in rollout and the full finishing/adaptive-boundary/corpus requirements pending.

Final integrated source/native/provider/cache/continuity/planning/publication checks345 passed+166 subtests in46.84s. Source-bound negative native checkpoints now preserve known ResponseContractError categories across resumes rather than reclassifying a known truncation as an unknown dispatch. Corrupt negative records fail closed without overwriting their bytes or calling the model. Follow-up86 tests+59 subtests passed; git diff --check passed. These checks establish mechanism compatibility, not product acceptance. A final tightened migration regression explicitly verifies old one-frame v1 proof bytes remain unchanged while v2 receives genuine new temporal observations.

2026-10-17 whole-candidate integration: source-only discovery, downstream native qualification, pure source-contract compiler and separate final-quality dispatch are implemented. Count changes rerank saved candidates, duration changes affect the proposal/qualification stage, source discovery stays reusable; plan_only misses stop before model sessions. Authored integrated checks127 passed+61 subtests, then focused review/batch/pipeline checks69 passed+63 subtests. These are mechanism tests, not story acceptance.

Candidate-only real diagnostic reuses genuine discovery from the already authorized120s excerpt (no authored candidate answers). Initial3 paid proposals exposed a physical scope bug: .18/.55 audio handles extended outside hypothesis windows; no review/export occurred. Extend physical context after the proposal without selecting it, preserving the original replies. The corrected continuation took151.14s and5 new remote attempts, warm0;0 ready/3 drafts/2 native-contract technical failures. One genuine negative rejects an unfinished story; other native answers used a payoff before a trailing reaction and filled dialogue rows for silent units. Preserve initial/raw results in temp/whole-candidate-trial-9e038c1ddfc34dffae00e14bba468ba7. Do not claim quality or full-pipeline cost acceptance.

Refine the candidate contract to bind opening/ending evidence to first/last actual cuts, with native checks still owning actual edges; establishing shots/reactions need not equal tiny catalog boundaries. Restrict dialogue schema and packet to exact spoken IDs. Review also found/fixed storage-path-dependent question identities, impossible state changes from byte-identical images, source-only quality false approval and collection-wide framing failure. Technical focus failure now retains an approved story as full-frame cinema with a visible partial outcome and no further model acquisition.

Frame-only actual diagnostic: all138/124/114 source frame records (unit/actual PTS/time base/JPEG SHA/index) exactly match prior per-owner extraction. Three fresh grouped contexts took5.49/4.42/4.24s using one FFprobe each and2/1/1 FFmpeg processes. Source unchanged, no model/API. This is component evidence, not an equivalent full-run speed comparison. A revised native spoken-contract trial is active (exec92965); app/semantic source frozen until it ends. Current remaining acceptance work includes full cold/warm source run, actual media/editorial review, finishing process/operation recovery, adaptive boundaries and held-out corpus.


2026-10-17 whole-candidate evidence: the targeted source-only continuation reached
3 native-approved edits, rendered/fully decoded all three in31.506s with no model
calls, and reused qualification in1.547s. Independent output-only review found
unfinished stories in two; it did not audition audio. Fresh production trial
standalone-whole-full-42169da759d2416982801596a27d9416 took137.439s,2 local/8 remote
transport starts,2 rendered outputs/partial status,1 technical micro-gap and2
context limits. Independent output-only review rejected both endings. These are
not editorial acceptance or equivalent workload speed claims.

Implemented mandatory output-only candidate_screen with private exact binding,
no omitted ASR/images or source clock in the viewer payload, and one optional
strict trim followed by fresh source+viewer checks. Original evidence/proposals
remain in history. Actual rebuilt trim cannot add footage or repeat unchanged
geometry. Tiny unspoken two-frame gaps are normalized before semantic review;
spoken gaps/exclusions remain protected. Combined initial integration:123 tests
and59 subtests passed. Real same-source candidate continuation is running under
session3564, phase blind-trim-contract; do not edit app code while live. Managed
finishing remains an isolated prototype and is not integrated or claimed complete.


2026-10-17 follow-up: initial blind gate rejected all3 candidates with3 new remote
requests/0 technical failures; unchanged warm0 requests. Explicit blocker-only
criteria and a concrete-or-null repair decision then retained1 complete local
story, leaving2 drafts;3 new remote requests,23.050s, warm0 requests/0.027s.
No repair was proposed in these actual answers. New source/native/negative-repair
regressions pass; combined candidate suite247 tests+104 subtests, final malformed
screen/observer guard85 tests+3 subtests. Media publication reused identical
validated video bytes (SHA lineage saved),2.973s including warm1.181s,0 models.
Audio audition and full editorial/corpus acceptance remain pending.

Finishing storage foundation moved into app/finishing_commands.py, with shared
OS lock extracted to app/file_lock.py and exact jobs compatibility re-exports.
Independent review reproduced a descendant symlink escape in the prototype;
production resolver now validates every descendant.35 new plus53 jobs/idempotency
tests passed, including actual abrupt child lock release. Store receipts use fake
media and do not prove real decoding. Worker/API/queue/resume/reference-serving
integration remains pending; see ADR0056. New full production120s trial session
25772 is live with app source frozen and the new cut-only gate.


Full trial session25772 is terminal:147.761s,2 local episode-survey requests,
1 remote map+4 proposals+3 source reviews+3 cut-only screens (11 remote,13 total),
1 accepted56.35s video and3 explicit drafts,0 technical failures, stable code.
The actual model did not propose a trim. Artifacts live under
 temp/standalone-whole-full-edd33a3b31404617bcb6b9a2d8070e4a/job-120s.
Warm full run explicitly forbade cloud transport/local model startup:6.677s,
0 new transport attempts, same output hashes, stable code. Fresh observer files
were archived before warm overwrite. These are same-source measured runs with
global paid exact-response caches preserved, not a flushed-cache comparison.
Independent output-only review is in progress; no audio/full-series acceptance
is claimed. All app source may now be edited again after the terminal trial.


Independent blind review of the latest actual56.35s rendered output completed:
 temp/blind-latest-review/review.json. Comprehension4/5,causality4/5,ending4/5;
opening3/5,pacing3/5,interest3/5. No critical distortion or dependence on omitted
source context found. Weaknesses: conversational opening,37.67–43.80s reaction
hold,short final settling tail. Dense output-only samples show the fall. Audio
was NOT auditioned. This is limited independent visual/subtitle acceptance of
one excerpt, not full playback/audio/corpus/default-rollout acceptance.

Next concrete finishing integration: freeze exact probe/audio stream, source,
parts/captions, style, resolved music/avatar and render-code contract; render only
from that command without today's profile/source/asset resolvers. Then wire owned
process/start gate, heartbeat/fencing, startup recovery, durable scheduling,
resume/cancel and deletion guards, and serve verified per-part references. Keep
legacy completed exports readable and unknown-parameter legacy interruptions
non-resumable. Prove real decode and process-kill/restart before switching routes.


2026-10-18 managed finishing integration: finishing_render freezes source SHA,
probe/selected audio, exact caption ownership, profile, music/avatar and rendering
compatibility; media emits full-decode/hash receipts. finishing_execution/worker
own durable queue/processes, startup recovery, explicit resume/cancel, heartbeat,
fencing and start gate. API/browser preserve operation UUID across ambiguous POST,
list server tasks and control existing commands. Same-job equivalent parts reuse
validated references without media copies. Legacy daemon render/copy owners were
removed after caller searches; legacy completed readers remain. Job lifecycle,
pruning, deletion/tombstones and idle shutdown now consult durable ownership.

Independent review reproduced3 boundaries: busy operation lock orphaned running
state; saved command absent from scheduler after a lost submission; changed inputs
during render retained old identity. Fixes include bounded operation-lock waiting,
retained terminal reconciliation ownership, exact POST recovery, and input checks
before each receipt/completion. Additional real Windows pointer publication race
retained a \\?\ namespace prefix in Path.resolve; normalize only canonical same-drive
namespace and retain escape/alias rejection. Empty SRT is valid for silent parts;
empty MP4 is forbidden. Whole real smoke initially found missing legacy focus and
HTTP/direct numeric default cache differences; held-center fallback and canonical
profile freezing fix those without inventing content.

Actual generated-media process trial stopped after first committed part, restarted,
mutated current plan/source descriptor/captions, resumed exact command, reused the
first receipt unchanged and fully decoded both outputs. HTTP actual range/preview,
POST replay and equivalent reference checks passed in the standalone diagnostic.
Permanent real-FFmpeg integration test is being verified. Root earlier combined
finishing suite:216passed/1 stale removed-helper test, then244passed/3 newly exposed
shutdown/path-race failures; these were investigated, not reported green. Focused
postfix suite133passed+77subtests;19 recovery-boundary tests and31 scheduler tests
cover review findings. Final combined verification remains to be recorded.

Same-job finishing reference lifetime is implemented; different-job large-artifact
ancestry/copy removal, adaptive audio/action boundaries, corpus/audio acceptance
and default rollout remain unfinished. Do not mark the full objective complete.


Final managed-finishing +candidate/media/publication/job integration verification:
539 tests and207 subtests passed in121.44s (one existing Starlette deprecation).
This includes the permanent real generated FFmpeg/owned-worker/HTTP test: first
part preserved across interruption/restart, original frozen captions/source
selection, exact POST replay, equivalent new-command reference, range/SRT/preview
streaming and read-only GET snapshots. Spectrum confirms880Hz selected second
source stream instead of440Hz first. Frontend lint, two smoke suites and build
passed during API integration. No model/network requests were used for finishing
work. Independent review findings and the Windows atomic pointer race have
regressions. Final focused worker/API check after localizing user-facing error text passed
59 tests and7 subtests in14.64s; session35873 is terminal.

Cross-job rendered/clean artifact milestone: replace clean/output media copying with
explicit source/episode-bound checkpoint ancestry. Publication v2 stores immutable
origin revision/filename references and verifies target bytes through that chain;
v1 and untouched legacy output readers remain. Render reuse requires the exact
per-part fingerprint after current candidate quality checks. Clean caches receive
content hashes and genuine full-decode receipts; old timestamp-only caches miss.
Small analysis snapshots remain independently copied, including audio extraction
until its consumers gain a separate source-evidence interface. Origins remain
protected by existing checkpoint dependents; no global source-equality lookup.
Validation: no-copy/readonly ancestry, corrupt or foreign origin rejection,
publication aliases, chain deletion guards, and real generated-media reuse with
encoding forbidden in the child. Rollback: retain v1 readers; invalidate caches
and rerender locally rather than converting old media proof in place.

Cross-job milestone verification completed:306 tests+35subtests passed in86.47s
across publication, clean/media, pipeline, jobs, captions and finishing. A final
120tests+2subtests passed in26.93s after legacy migration fixes. One existing
Starlette deprecation warning, no skipped tests in these root runs. Fresh source
hashes and selected music/avatar bytes bind render identity; independent review
reproduced the music same-stat hole before its regression fix. New real generated
H264/AAC publication test fully decodes parent and resolved child, streams actual
GET/HEAD/Range/SRT bytes, verifies no child media copy or GET writes, and proves
parent deletion409 until child deletion. Real clean ancestry test forbids FFmpeg
in child after parent's genuine full decode. Library migration originally broke
unowned v2 publication identity; raw-owner binding plus common known-effective-
owner chain validation preserves additive migration and rejects foreign hops.
Small extracted audio snapshots still copy; adaptive audio/action boundaries and
full editorial/audio/corpus acceptance remain unfinished. No paid inference used.

Adaptive boundary implementation (active): existing perception uses500ms RMS and
fixed speech margins0.18/0.55s, insufficient to locate short non-ASR sound tails.
Measure20ms selected-track PCM only near proposed edit edges, with actual source
PTS/discontinuities and immutable source/stream/window/tool identity. Reuse exact
local/explicit-ancestor observations before decoding. Pure compilation may choose
relative local quiet valleys within source/omitted-speech/exclusion bounds, before
native and cut-only reviews; never edit a timeline after its approval. Steady
background sound does not prove a continuing action, and waveform/motion signals
do not establish semantic completion. Strong unresolved tails remain visible as
candidate-level uncertainty. Preserve legacy fixed-margin plans without this
versioned evidence. Validate synthetic tones/decays/gaps/offset tracks and the
authorized120s source before enabling the new policy; no new paid calls yet.

Audio boundary implementation/qualification verification:176tests+73subtests
passed before final optional-note changes; final focused147tests+53subtests
passed after them. Packet-size/offset/missing-audio regressions also passed in
the17-test focused run. Actual two-track PCM proves selected stream and source
clock; codec packet sizes do not change20ms measurements. Existing legacy
geometry stays unchanged without versioned evidence; changed geometry cannot
reuse old native approval, and framing reproduces it exactly.

Authorized120s local calibration temp/bqa-a4f313df01c9:4 existing candidate
proposals,10 bounded audio decoder starts,2.5498s; warm0.04127s with decoder
forbidden/0starts. No model calls or publication. Source-only evidence untouched.

Fresh ordinary full-route trial temp/standalone-audio-full-365a574e33ab4286a78c3099dc82402c/job-120s
finished245.172s with2local+16remote actualstarts (including2format corrections),
174973 reported tokens,0ready/3rendered drafts/0technical failures. Code stable.
Four source-aware approvals failed cut-only story checks; another candidate hit
the existing frame/context capacity. Source discovery proposed different stories
than the earlier147.761s run; this is not an isolated audio-performance comparison
or equivalent cold speed claim. Exact warm repeat with DeepSeek fetch and local
startup forbidden:5.656s,0new transports, same needs-review outcome. Fresh reports
archived under benchmark/fresh before the warm observer overwrote current reports.

Controlled old useful proposal/new audio geometry first returned all source
criteria true but optional context suggestions in blocking issues (temp/audio-isolation-9c1e593de8fe).
Native/viewer schemas now accept optional notes; prompts distinguish local-story
requirements from optional context or whole-episode resolution. Historical issues
remain blocking; no automatic reinterpretation or forced true criteria. Final
controlled requalification temp/audio-isolation-2b62ab5dc5fe passed source+blind
in25.7739s with3remote starts (one source format correction). This is a bounded
component experiment, not another full discovery success. Pure compiler and real
media rendered56.17s viaNVENC in6.8256s, fully decoded before and after immutable
publication; render-summary.json owns hashes/path. Audio was NOT auditioned;
independent editorial/corpus acceptance and robust full discovery remain pending.

Visual-context milestone (active): actual capacity-limited candidate has82 units,
75 retained (28spoken/47silent),172 images. ASR pause intervals each receive three
images even when they share the same original shot; this is not proportional deep
inspection. Keep a source-owned midpoint per observed unit, actual cut anchors and
original shot entrance/exit observations. Use existing source optical-flow samples
as nonsemantic hints for locally prominent motion before/peak/after observations.
Explicit requested-unit enrichment adds quarter points, not the same already-seen
three images. All images retain exact source PTS/owner/SHA; missing action evidence
can still veto/request more, and provider capacity remains enforced. No global
source survey or accepted history rewrite. Verify actual packet sizes on the
capacity-limited source before any new inference, then bounded ordinary native
qualification; independent product/audio acceptance remains open.

Visual observation milestone verified:131tests+53subtests passed. Real
temp/visual-packet-233e3218e808 comparison extracts143actual owned images instead
of172, eight pages,7.4194s and0model calls. Half-open ownership/pixel hashes validate;
source history unchanged. The identical automatic proposal then reached ordinary
native source+viewer checks in20.6329s with2remote starts. Source approved, viewer
rejected an unfinished local ending; no trim proposed, no publication/false ready.
Warm repetition with remote fetch forbidden took3.8605s with0new transports.
Cold/warm qualification summaries are separately preserved. The old context
failure for this case is resolved; proposal usefulness and full editorial recall
are not. No source survey restart or new provider/model/dependency was added.

Next concrete investigation: candidate_proposal currently sees only ASR/catalog
plus sparse-map hypothesis, while deep images arrive after the proposed ending
has been chosen. Evaluate giving that EXISTING proposal request a compact owned
shot/motion storyboard, without a new model pass or prior verdicts. Measure actual
physical payoff coverage and resulting proposed cuts before another whole-source
trial. This is a causal hypothesis from the observed long/unfinished proposals,
not yet implemented or claimed to improve recall. Retain independent source and
cut-only gates and separate listening/corpus acceptance.

Visual proposal implementation (active): feed compact original-shot representatives
and prominent-motion before/after images into the EXISTING proposal query. Reuse
the owned frame adapter/pages; keep source-unit IDs/ASR and image PTS/hash binding.
Use the provider's existing visual capacity with chronological coverage first;
sampling is hypothesis support, never a completeness/absence/selection proof.
Deep source review still receives only its independently built actual-cut packet,
not proposer rationale/verdicts. Cache-only/plan-only lookup precedes extraction
and sessions. Measure physical coverage first, then one bounded same-context
proposal→source→viewer trial before another whole-source run.

Visual proposal/capacity results (2026-10-18): the first proposal used48images in
3pages and selected four groups across25.54–116.44s. Its temporary test omitted
duration preferences; preserve that limitation in benchmark/initial-visual-proposal
and do not call it an equivalent default-setting comparison. The original162image
native packet needed9pages. Official DeepSeek documentation disproved the old
8page/4MiB app limits: implement actual600image/32MiBsingle/64MiBraw/48MiBbody
protocol bounds with exact pre-read base64/JSON sizing. No Files API or new upload
scope. Real source review then approved9pages in11.2692s,29042reportedtokens.
The blind question initially hit a cached pre-dispatch canonical-schema capacity
rejection. Delegate capacity to actual compact wire; migrate ONLY that known
unsent negative and preserve successful/unknown keys. A subsequent12.989s component
repeat reused proposal/source paid responses and made1new blind call,26645tokens,
4.64s provider time. Viewer rejected unfulfilled final request/unanswered speech;
repair=null, needs_review, no publication. Source approval is not story acceptance.

Independent read-only subagent vision_capacity_review reproduced a P2 duplicate
paid transport: corrupt optional diagnostic run metadata was caught as invalid
cached answer. Separate optional auditing from cache validation; malformed audit
JSON/nonobject/I/O cannot resend a valid answer. Mock regressions plus focused
candidate/DeepSeek/native/viewer/pipeline suite:184tests+83subtests passed9.06s;
one existing Starlette deprecation warning. ADR0061 documents protocol/preflight
and cache compatibility. No real network in tests.

Next bounded quality hypothesis: choose a visible/spoken local payoff first,
backchain necessary setup/development, stop after outcome/reaction before a new
unfulfilled topic. Existing proposal only; no supplied old verdict, new stage or
weakened gates. A separate same-context trial uses the actual persisted45–90s
preferred/120s maximum defaults. It is not a cold discovery comparison. Keep app
code frozen until terminal, record negative outcomes as well as useful output,
then verify exact warm reuse with transports forbidden. Full source discovery,
listening/editorial/corpus acceptance and audio.wav consolidation stay open.

Payoff/default component trial completed in26.9568s at
temp/visual-payoff-defaults-3b835a323d2f:3remote starts,45509reportedtokens, no format
correction/trim, source+blind ready. Automatically chosen semantic groups:
25.54–35.46,37.86–46.40,47.84–54.10,56.84–87.73s; measured audible cuts:
25.54–35.61,37.73–46.55,47.65–54.31,56.84–87.90s; total56.61s. No manual selection
or previous verdict supplied. This fresh component job omitted copied motion
hints, so its proposal had27shot images/2pages and native99images/6pages. Compared
with the preceding component, prompt, duration preferences AND motion hint
availability changed: do not attribute the outcome solely to prompt or claim an
equivalent speed/cost gain. Exact fresh records and limitations are archived in
benchmark/fresh. Warm6.7406s with DeepSeek fetch and LocalVision startup forbidden
made0new transports and remained ready. Pure compilation/source integrity passed;
actual h264_nvenc render+immutable publication+complete published-file decode
took7.4298s. Revision263f8d6e8008e4482031709361faaf35f9732cc2fe2d97cca023e13d7d915b19,
video SHA bfec903213ded1021df73c2a7abf5c9c931921a0d7f7170b608c8d321ffc7060.
This is actual component integration, not end-to-end discovery or audio audition.
Independent output-only frame/subtitle editorial review is underway; audio and
the full corpus remain unaccepted.

Fresh ordinary full-route validation started with the same authorized120s raw
fixture and no semantic answers in the input:
temp/standalone-visual-full-44dc77fe371d49728554e5d8e16f4bbb/job-120s.
The observer preserves paid exact-response caches, records actual new transports
and stable app code, uses default standalone preferences and real cinema rendering.
This independently redoes discovery instead of manually injecting the useful
component proposal; do not compare its timing as an identical historical workload.
App source stays fixed during the run. Full editorial/audio/corpus work stays open.

Independent output-only review of the56.61s component is now saved under
temp/blind-payoff-output-review/review.json. Its own frames/SRT (no source or
qualification access) score interest/opening3, comprehension/causality4, pacing2,
ending3, framing3 out of5. The fall remains visible near31s, but roughly25s of
aftermath and a small cinema image weaken the short. Root inspected the30s–end
contact sheet and confirmed the long visual aftermath/whole-frame layout. This
does NOT meet the proposed ending/editorial acceptance threshold despite both
model gates approving. No continuous playback/audio audition occurred. Keep it
as a reviewable component artifact, not an accepted product-quality demonstration.
Do not adjust gates or prompts during the running independent full trial, and do
not run repeated paid checks of the same negative merely to seek approval.

Fresh full trial terminal:114.8861s,2local/0remote starts,0outputs,
pipeline_code_stable=true. The first local survey batch completed353tokens; the
second (two windows) exhausted2048tokens, invalid JSON/finish_reason=length. No
paid request occurred. Sparse survey redundantly asked an unbounded question
list per window before the full map generated questions again. Simplify that
observation contract to bounded factual summary+uncertainty; full-map question
ownership and complete ASR/window/frame coverage remain intact. No output/token
budget increase or model retry role. The exact malformed output was not retained,
so do not claim which individual field repeated. Updated authored survey fixtures;
131tests+36subtests pass18.92s with one existing Starlette warning (ADR0062).

Ordinary full route resumed in the same job after preserving initial outcome,
code identities/timing and transport history under benchmark/initial-failure.
The resume's resources/results go to benchmark/after-survey. This is explicitly
not a fresh cold comparison. App code again stays fixed until terminal.

Read-only audio_evidence_scope follow-up mapped both remaining copied WAVs:
root ASR audio.wav and nested media-evidence/audio.wav. The latter has source
PTS/gap semantics and must not be substituted by the ASR PCM. Next storage change
can exclude nested transient PCM from snapshot copies, and reuse root PCM only
through complete validated explicit ancestry plus a source/stream/extraction/tool/
actual-bytes/full-PCM receipt. Preserve local extraction fallback, old readers
and parent bytes. Ownership/lineage failures must propagate before any PCM read.
See the agent's concrete function/test map; this storage change is NOT implemented.

Post-survey full-route resume completed193.4913s with app code stable. Actual new
starts17=2local+15remote (map1,proposal5,source5,blind4), with4707local and183331
remote reported tokens. No format correction or trim call was needed. Five genuine
discovery hypotheses produced1native-accepted50.13s rendered/published clip,3draft
proposals (not rendered because accepted media exists),4declined records and
0technical failures. The selected automatic story is not the injected earlier
component selection. Full-decode publication revision:
fba66bb0361ead01cc238b8b2241ae9a64b2788cdf73dac45a6f3b7315ea658f.
Fresh post-fix records are preserved in benchmark/after-survey/fresh. Exact full
warm5.8440s with DeepSeek fetch/LocalVision startup forbidden made0new transports,
retained identical standalone outcome and export hashes. First failed114.8861s
attempt remains separate; do not combine these into a cold comparison or omit
the initial failure. A fresh output-only agent is evaluating the actual full-route
video, without source/qualification/previous review input. Audio and wider corpus
remain unaccepted; keep rollout opt-in.

CRITICAL editorial regression in that full-route output: fresh independent
temp/blind-full-visual-output/review.json scores interest3/opening4/comprehension4/
causality3/pacing3/ending4/framing2. It flags30.8–30.9s jump before fall. Root then
compared ORIGINAL59.5–66.5s at0.5s intervals (actualPTS; no model calls), saved
temp/full-fall-source-check/source-59.5-66.5.jpg. The automatic gap60.34–64.79s
really removes the girl's rise61.019 and visible falling62.020→62.521s, retaining
only aftermath. This is an introduced causal/action defect, not merely original
anime style. Both native and blind gates missed it. Preserve the raw ready record
as a reproducible failure; this export is NOT editorial acceptance or a finished
quality demonstration. Audio/continuous playback were not assessed.

Next REQUIRED implementation: source-backed omission/join evidence in the SAME
native review query for every actual introduced gap, showing omitted observations
and both retained-edge anchors explicitly. Existing retained-edge safe booleans
and three speech-backed story proofs do not establish that a consequential silent
action can be omitted. Version the new case policy so old records remain readable;
new whole-candidate jobs must prove gaps before blind/publication. Do not auto-keep
all motion, invent action truth from optical-flow scores, merely lower a threshold
or rerun the same paid verdict until it approves. A read-only join_contract_design
agent is checking the smallest bounded schema/validation/repair path. No join
contract change has been implemented yet. This remains active goal work.

Source-join implementation now present (ADR0063): new analysis/case/scoped policy,
actual-audible gap descriptors with retained anchors/own omitted images, positive
coverage/ownership checks in native approval, meaningful negatives and legacy
readers. Root176tests+83subtests passed8.62s; subagent38tests+71subtests includes
two-gap foreign-image regression. Additional gap observations use actual decoded
PTS. No extra model stage or increased output budget.

IMPORTANT first real join regression FAILED editorially despite mechanism success:
temp/source-join-regression-6aabecbcd8ee reused the SAME defective automatic edit,
20.2555s, native+blind both ready, not published. New join row explicitly says
the fall was omitted but calls it incidental because later reaction/examination
remain. Thus the gap evidence makes the specific semantic policy mismatch visible;
it does not yet solve it. Preserve this false positive. Tighten the source-join
instruction to distinguish inferable consequence from preserving an actual visual
turning point: consequential action causing retained reaction/changed state must
remain; neutral gestures/waiting/repositioning may still be omitted; redundant
requires the same retained event, not aftermath. No source-specific timestamp or
old verdict is sent. One changed-policy regression is required; unchanged paid
answers are never retried just to seek approval.

The stronger v1 instruction also FAILED: temp/source-join-regression-1befb9f74cad,
16.9115s, same actual edit, native+blind ready; join explicitly replaces the fall
with later pain. No publication. A separate explicit reasoning-low capability
experiment (ordinary factory unchanged) exhausted8192generation tokens in48.188s,
no valid JSON and no blind call: temp/source-join-reasoning-4c01a94e34c7. Preserve
that failure; do not enable this mode, continue increasing allowances, or silently
retry. The experimental _ask8192 branch/test has been removed from app; ordinary
4096 external allowance and factory remain. Experimental source records document
their actual historical8192request.

Required structural correction v2 (in progress): collect factual omitted before/
after change separately from the model's safe/classification opinion in the SAME
query. Distinguish minor motion/speech from physical_event/object_change/reveal/
scene_change/unresolved. A substantial omitted event without a before/after
witness of the SAME event within ONE continuous retained cut cannot approve,
regardless of safe_to_omit=true. Retained edges across the gap/aftermath are not a
witness. This is not all-motion retention and does not infer semantic truth from
optical-flow scores. Preserve v1/no-policy readers; new jobs default to v2. The
pure factual gate/ownership tests are being implemented by the same bounded
subagent; root owns prompt/transport integration. No new model role/pass.

V2 real regression SUCCESSFULLY REJECTS the actual bad automatic edit:
temp/source-join-regression-eb91875c50a4,18.5843s, same_actual_edit=true,
needs_review after native source check; no blind/new proposal/publication. Its
factual row identifies standing→fallen physical_event, with own omitted frames,
no retained same-event witness. Other gaps identify hand movement/puddle changes.
This demonstrates combined v2 task/gate on one source, not general semantic
reliability. Mechanism suite184tests+108subtests passed8.96s before the static
counterexample refinement. Static none/speech_only now permit identical pixels
at different owned PTS; material/minor-motion claims still need distinct source
pixels. Subagent46tests+102subtests cover that distinction (no all-waiting keep).

Implementing one proof-driven restoration as the ALTERNATIVE to existing blind
trim, sharing the same single editorial repair attempt. Only grounded v2 source
before/after catalog runs may expand prior semantic core; do not restore unseen
material or other gaps. After remeasuring audio, actual retained content must be
a strict superset, new footage only inside original actual gaps, no outer-bound
expansion and no max-duration overflow. Preserve old record/history, then fresh
source+blind checks. A second restoration/trim is forbidden. Root workflow58tests
pass1.52s; pure proposal/binding/ownership tests remain with the bounded subagent.
No new model pass until a valid changed edit exists; no repeated restore loop.

Pure restoration+workflow integrated; root197tests+149subtests passed8.93s.
The first real automatically derived restoration stopped BEFORE model transport
in0.9723s at temp/source-join-restore-6e1432c47523: audio remeasurement changed
the second retained start64.62→64.79, losing0.17s of prior content. The strict
superset guard correctly rejected it; do not weaken that guard or change approved
geometry during rendering. Original actual cuts and source semantics are saved.

Minimal whole-unit repair refinement under review: only immediate catalog neighbors
of an observed restored run may be included when they own the OLD audible edge
of that SAME proved gap and were already partly retained as an audio handle.
Keep strict adjacency, same-gap/outer bounds, no other-gap crossing, no repeated
closure. The fall's right neighbor64.147–64.79 owns the old64.62handle; including
that complete physical owner should preserve prior content without a hidden new
geometry override or case-floor interface. Unrelated waits/gaps remain excluded;
actual delta/maxduration/fresh-check guards remain unchanged. The bounded subagent
is implementing this owner closure and regression; no further model run yet.

Immediate owner closure is implemented and frozen. Focused combined suite200tests
+149subtests passed8.85s. Independent read-only review found no actionable issues
and separately ran56story-contract tests and42candidate-analysis tests. The real
automatically derived restoration at temp/source-join-restore-6f507c01ab1e passed
strict geometry guards, then fresh source+blind checks in16.8747s,2remote calls,
39640reported tokens. Actual retained interval21.86–83.92s includes all old footage
and fills only its four grounded gaps; no manual cut/proposer override. Warm replay
with fetch/local startup forbidden took3.293s,0newcalls, exact same plan. Compiler/
NVENC/full-decode integration produced62.06s in7.6489s, revision7557e52e6dc05368c04644fd5dc075b64cf5a832d67f85039074dc87fae31c76,
videoSHA90682c4d45305a0b88558879fb0866a21ac86f3668c684e4a31b6bffbcb73df7.
This remains controlled existing-negative repair, not fresh discovery acceptance.
Independent output-only agent is reviewing the immutable output. Audio was not
auditioned. Ordinary full-route resume under unchanged app code is now running
through temp/run-source-join-full-route.py, exec71138, benchmark/source-join-v2.
Do not edit app source or rerun that process while active.

Ordinary v2 full-route resume TERMINAL101.8517s/9newremote starts, appcode stable,
partial with1native-ready/3draftproposals/1model-output technicalfailure. It still
approved the SAME defective50.13s edit; this is FAILED semantic acceptance. Exact
warm5.688s0newcalls with fetch/localstartup forbidden preserves both falsepositive
andfailure. Immutable bank benchmark/source-join-v2/fresh. Independent image/page/
ledger audit found no transport/indexbug:124fullframes contain all108controlframes
+16extras outside the fall; sourcejoin4 ownimages/time/geometry identical. Model
described standingmale while ignoring visible girl's rise/fall. Restored-output
review confirms fall/causality4, but pacing/ending3, no audio/continuousplayback.

Gap-focused native-page presentation was experimentally implemented+206tests/
149subtests passed8.98s. Same failedfull proposal/actualcuts/124sourceobservations
then ran at temp/gap-focused-source-0376957d6224,26.4505s,16pages,2remote starts,
51873reported tokens. Both rawresponses stilldescribe allgaps neutral; first
misnested retained_witness, correction omittedproofmotion, technical_failed.
No source/blindapproval/publication. Experimental code/tests archived underjob/
experimental-code and removed fromproduction because no demonstrated benefit.
Do not retain speculative complexity or repeat identicalpaidquestions untilpass.
Next isolate basic image/state perception from the overloaded story judgement
before designing further production changes. Audio snapshot consolidation stays
open and independent; do not confuse controlled repair with whole-goal completion.

Narrow image capability diagnostic: temp/basic-state-perception-31084a2ebf69,
3.561s, same6originalimages as3pairs; answer misassigned whichimages formedpairs.
Sameobservations/schema on3labelled left-before/right-after images then correctly
recognizedphysicalchange vsstaticcontrol: temp/paired-state-perception-5c28bb79bc9a,
2.980s. This motivates explicitnavigation, not a semantictruthclaim.
Productionnative now prepends one labelled omitted-endpointpair peractualgap,
with originalIDs/PTS and image-to-frame mapping; ALL fullsourcepages remain.
Sourcepolicyv1/absent andproposal/blindinputs unchanged. Totalpagecapacitychecked
before dispatch. Focused203+149tests passed8.94s; independent46candidateanalysis
tests passed after additional actualpagecapacityregression; no reviewfindings.

Samebadordinaryproposal/actualcuts/124observations attemp/join-pair-source-6244c0b4baf3
nowrejects actualfall,19.225s,1remote,26368tokens,no blind. Onegrounded repair at
temp/join-pair-restore-9a88405c482f restored ONLY source60.75–64.62 preservingallold
cuts,16.093s, but freshnative remainsneeds_review withincorrectothergapclaims.
No secondrepair/blind/publication. Preservefailure, don'trepeatedlyaddmissinggaps.
Ordinary route with pairedoverviews nowrunning, exec24105, script
temp/run-join-pair-full-route.py, benchmark/join-pair-overviews; sourcefrozen.
Read-only bounded architectural subagent examining duplicatednative/story and
blindstory responsibilities; no newpasses/roles/loops are authorized by that design.

Ordinary paired-overview route finished122.898s/9newremote starts,0accepted/
3rendered needs-review drafts/0technical failures, stablecode. Warm5.641s0newcalls
with transports/startups forbidden, exactsameoutcome. No false-ready replaced the
knownbadselection; priorcommittedrevisionremainsasrequiredbypublicationrecovery.
This is honestnegative+usable-draft behavior, notsemanticproductacceptance.

Bounded simplification experiment implemented sourcepolicyv3 (sourcefidelity only;
viewerowns story), same sourceimages/actualedits, noadditionalstage.211tests/
153subtests passed11.81s. Fixed controls attemp/source-fidelity-controls-7d037bd8c411:
defective124images needs_review15.691s; fall-restored54.00s/121images needs_review
13.564s withinventedobjectactionandspeechinsilentunit. Thus specificity FAILED.
Exactwarm3.446/3.399s0newcalls. Defaultnotchanged, no repair/proposer/publication.
Code/tests archived underexperimental-code, thenremovedfromproduction; priorv2
behaviorandownerclosurepreserved. ADR0064 and native-source-fidelity ExecPlan close
this experiment asfailed, nottheoverallgoal. Stop sourceprompttrialloop; remaining
storage/audioevidence consolidation and corpus/listening acceptance stayopen.

Final production-v2 integrated validation after experimental removal:292tests/
179subtests passed26.25s (existing Starlettewarning). Covers candidate source/viewer/
compiler/framing/pipeline, DeepSeek compact transport/cache, survey/standalone
analysis, question ledger and continuation. git diff --check no whitespace errors
(existing LF/CRLF warnings). All actual model/exec runs above are terminal.

Next bounded storage milestone: stop copying rootASR audio.wav and nested transient
media-evidence/audio.wav in inherit_checkpoints. Resolve ASRPCM through the already
explicit fullyvalidated checkpoint lineage and a new producer-owned receipt binding
source/stream/extraction/toolbytes/size/SHA/format/fullPCMread. No newservice/DB/global
registry, no ancestor mutations/receiptupgrades. Invalidlineage failsclosed before
PCMreads; corrupt media misses and extracts in the current job only. Receiptless
ancestors conservativelymiss. Current completed ASR should not require any WAV
extraction: prepare PCM lazily only for actual transcription/repair, preserving
existing transcript compatibility. Separate source-PTS perception WAV is never
substituted for ASRPCM. Full declared-length PCM validation belongs to the new
preparation boundary before either ASR call. Keep inference.py byte-identical:
preparation_identity hashes its entire code, so an input-only guard there would
unnecessarily invalidate every existing automatic transcript. Direct standalone
inference CLI truncation handling remains a separate known limitation.
Root owns analysis/processing/inference integration+tests/docs; bounded child owns
new app/asr_audio.py +tests/test_asr_audio.py. Validate lazy actualanalysis flow,
whole-chain owner/source guards, selectedstream/tool/same-statcorruption, cancellation,
plan-only ancestry and a real dual-tone FFmpeg extraction without any inference.

ASRPCM module/root integration implemented. Module28tests and rootanalysis/
snapshot/runtime/providedASR integration67tests+30subtests passed (before final
combined verification). Independent review found one concrete source-mutation
duringextract provenance race; fixed by current source/tool rehash after PCM
validation before cachedreturn/mediareceipt publication, withsame-stat regressions.
Input protocols file/pipe only. inference.py unchanged; existingASRidentity preserved.
Agent-generated root test dirs moved under temp/asr-agent-test-artifacts (no deletion).

Final real synthetic2-track component temp/asr-audio-ancestry-29dcda293d94:
stream1 measured880Hz, extract0.5032s/reuse0.2594s, 2-hopthroughplan-only, extraction
forbidden onreuse, no PCM/receipt snapshotcopies, same-statcorruption regenerates
onlynewchild andparentbytes/mtimeunchanged.0ASR/remote calls. Actualauthorized120s
route poststorage-refactor resume38.953s with DeepSeekfetch/localstartup/PCMprepare
all forbidden, same3rendered needs-review drafts/0accepted. This is codechanged
resume, notordinarysame-code speedcomparison or editorialsuccess. ADR0065 records
the final interface, legacy receipt misses and separate standaloneCLI limitation.

Final ASR/source integration360tests+196subtests passed60.97s (existing Starlette
warning only). Includes PCM/preparation/snapshot/ASR/runtime/providedinput/lineage/
continuation/semanticidentity plus nativecompiler/viewer/framing/pipeline. Independent
same-stat source-race reproduction nowrejects before audio/receiptpublication,
requiresfresh extractionafterrestore;3mutation regressions independentlypassed.
Tracked gitdiff whitespace andexplicitcheckofnewapp/test/ADRfiles clean. All real
model/exec/testprocesses terminal; no sourcefidelity-v3 productionbranch remains.
Storage PCM milestone complete; overallgoal remainsactive with semantic/corpus/
listening/rollout acceptance and remainingarchitecture work open.
