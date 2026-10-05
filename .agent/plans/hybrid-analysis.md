# Goal
Offer explicit local-first analysis with DeepSeek checking only uncertain or malformed local answers. Continue locally if the account, network or remote model cannot provide a usable answer. Preserve fully local and explicit full-cloud modes.

# Current state
Sequential local vision sessions and durable stage checkpoints already exist. The optional DeepSeek adapter validates source IDs/schema, caches exact requests, verifies account funds, and journals reservations before paid requests. A full local quality review is in progress; pause it before changing provider identity.

# Constraints
All files and dependencies stay in F:\new_prodject. No secrets or raw HTTP errors in review reports. No paid automatic retries and no invented total spending ceiling. Self-reported confidence is a routing signal, not calibrated accuracy. Cancellation must propagate.

# Implementation
1. Wrap local query sessions. Route explicit uncertainty, invalid answers, focus confidence below .75 or unconfirmed visible speech, and classifier confidence below its existing .85 safety threshold.
2. Validate remote answers. Accept usable focus from .55 and conservative classifier decisions; retain local results when the remote review remains uncertain. Record unresolved checks and disable repeated unavailable remote attempts across sessions/restarts of this job.
3. Include routing/model profile in all affected stage cache identities. Do not reuse prior local decisions as hybrid-reviewed decisions.
4. Add explicit API/UI mode and review warnings. Test routing, fallback, cancellation, cache isolation and persistence without real API calls.
5. Resume the test episode under hybrid mode, retaining factual preparation/transcription checkpoints. Record actual remote cost estimates and finish export/story/crop QA under the main project plan.

# Validation
Existing pytest suite and UI VM regression tests. Verify local mode never constructs a cloud client; confident hybrid answers never send remote requests; funds/network failures preserve valid local answers; invalid local+unavailable remote returns the original local failure; no repeated paid request for unresolved identical evidence. Inspect real job status and review journal, without claiming export quality before review.

# Risks and rollback
Confidence can be wrong in either model; source/time validation and conservative retention still apply. Unknown billing halts cloud use, while hybrid continues locally. Choosing local restores offline routing; provider-specific cache identities prevent silent interchange of decisions.

# Progress
- [x] Wrapper, cache identity and safe review journal.
- [x] API/UI choice and warnings.
- [x] Tests and resumed real episode.

# Observed validation
Root ran 219 tests and 74 subtests in 17.28 seconds; UI syntax check and 6 Node VM tests passed. These include local-first routing, classifier/focus thresholds, malformed local results, missing funds/network failures, cancellation before or during inference, durable no-repeat behavior and focus stage cache invalidation/reuse. All tests use fake API clients/accounts. Real server restart and retry restored job 17009d33-5efd-4dfb-8907-a44f5b69d9dd as hybrid; preparation/repaired ASR reused, old model decisions invalidated by provider profile. First ten visual fragments made no cloud requests; cumulative prior diagnostic cost estimate remained USD 0.0008502 and last verified balance USD 0.06. Full montage QA remains pending under the main plan.

All 36 initial visual fragments subsequently completed without triggering remote review. Added source-image paths, local uncertainty/confidence and accepted remote confidence to the safe job journal for review navigation; the 18 hybrid tests and 11 subtests passed again in .43 seconds. A final checkpointed reload restored all 36 visual checkpoints and continued the 9B story stage. Server PID 31352 is owned by the local project runtime; current observer writes qa/runtime-observation.json, earlier segments remain qa/runtime-before-hybrid.json and qa/runtime-hybrid-visual.json. No claim of completed montage quality is made.

# Full-run review and accepted scope change
The hybrid story-only draft produced 13 parts/1053.683s, but source review found retained opening/closing credits, a malformed ending partition and next-title speech preserved because narrated_title_units was empty despite visible_title_units. Pause before rendering these errors. Add domain validators inside hybrid review routing (malformed source partitions are uncertainty even with high confidence); bump credit-edge/closing stage versions, and independently verify visible spoken titles without depending on the optional narrated-title list. Protected real dialogue remains intact.

The user then explicitly selected DeepSeek as primary for story/plan, with local crop/render. Add explicit deepseek_plan API/UI provider; initial multimodal source analysis and all story/title/continuity stages use DeepSeek, final temporal focus remains local Qwen9. Source preparation/ASR are reused, initial local model decisions are invalidated. Fix cloud global output allowance to1800 and use a bounded UTF-8 context allowance below the20KB client request limit; the local5300-token context limit must not be applied to the remote byte estimator. No extra spending cap or paid auto-retry is introduced. Observe account preflight and preserve paid response cache; review actual resulting plan before exporting.

The explicit plan mode and partition/global validators passed 238 tests plus 81 subtests (16.83s) and seven UI checks. A known-cost malformed focus answer had halted cloud use: all eleven paid entries were completed with confirmed within-reservation costs. Explicit recovery preserved USD0.0032700 peak-rate cost, blocked the failed request digest and verified USD0.06 funds. The new full cloud-plan run is active; no quality acceptance is claimed before export review.

Full remote visual pass completed all36 windows. Two130-token credit responses failed; the second private diagnostic confirms finish_reason=length and a copied JSON schema instead of concrete classification values. Preserve paid failed request blocks, clarify schema-instance instruction for future requests, and support legacy valid-cache/blocked-digest identities so the prompt fix cannot repay rejected evidence. The rejected paid decision falls back to conservative source retention; unknown costs/funds still stop paid work. No full export acceptance yet.

At the user's explicit request, remote output allowances now expand short130-token classifications to512,650-token selections to2048 and1800-token global review to4096 (explicit replies up to8192 supported). All prior valid response identities remain readable; both previous schema-wording digests plus original caller allowance are checked for paid rejection blocks before balance/submission. Every actual reservation uses the expanded output allowance. Focused66 tests passed1.502s. Full run resumed using cached36 visual and finished story scenes, with three failed paid digests blocked; no old rejected request was paid again.
