# Honor explicit condensation and balance part durations

## Decision
Keep complete selected source units with their visual setup/reactions. Story condensation must partition actual unit IDs into retained units or explicitly omitted units with a supported redundancy/waiting reason. Current images include an exact frame-to-unit mapping in the prompt: frame numbers are not source-unit IDs. Missing or contradictory evidence preserves the scene with warnings.

Validated selections use `unit_selection_version=1`; the planner expands selected speech to complete replies and lead/tail handles but does not restore every intentionally omitted exchange. Legacy/fallback selections keep their speech-restoration behavior. Verified question/answer and ASR-prefix protection can restore needed context.

Global review may flag an event `global_excluded` only with an explicit reason, concrete evidence and confidence >=.85. Uncertain events remain. Dependency closure and verified speech context can rescue an omitted prerequisite. Partial/malformed partitions cannot authorize deletion.

After condensation, parts aim at the average duration of the remaining material and minimum feasible number of <=90-second clips. Actual complete reply boundaries are preferred near that target; silence can be split without filling each part to the maximum. Large indivisible replies can still cause unequal parts. No target retained percentage or invented source timestamps are imposed.

## Compatibility and rollback
Story version 9 invalidates derived decisions without repeating unchanged initial visual/ASR evidence; unchanged paid request content still reuses validated response caches. Refined uncertainty is explicit. Incomplete global descriptions cannot authorize deleting whole events. Pacing version 7 reviews margins from .75 seconds in units up to two seconds with three interval views plus immutable before/after context, exact neighboring replies and retained-evidence flags. Neutral scenery is separate from meaningful action/reaction; explicit story changes are protected. Repetition must cite a retained witness; a removed copy cannot justify deleting another. Sheet-local letter IDs prevent ordinal confusion. Version6 validated remote checkpoints can migrate after domain validation; local-fallback sidecars prevent migration. Witnesses are mandatory only for repetition deletions. Pacing never authorizes production-credit removal. Planner version 8 repacks when replies require extra parts and limits shot preference to nearby boundaries. Prior completed jobs and cumulative costs remain intact.

## Validation
Pacing8 makes narrative/emotional function explicit without the user's abstract object examples. Evidence must explain the specific loss on deletion and be grounded in current images and neighboring events. Physically unchanged silent reactions can be consequential; movement alone is insufficient. Cached pacing7/6 choices are not migrated to this changed prompt. The completed real-source comparison uses pacing7; do not claim that export validates pacing8 model judgments.

Regression checks cover intentional omission versus legacy restoration, whole visual units, safe fallback partitions, global exclusions/dependency rescue, question preservation, equal silent parts, discontinuous cuts and complete replies near the balancing target. Real-source checks are recorded separately in the quality audit.
