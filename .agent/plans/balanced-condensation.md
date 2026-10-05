# Goal
Restore meaningful condensation without cutting visual causes or dialogue endings, and distribute Shorts to similar lengths rather than maximum-length parts plus a short tail.

# Current state
Latest real export retains 1369.972 of 1420.222 seconds versus baseline 1197.228. Whole-unit retention is correct, but the model preserves nearly all units, planner restores every reply, and global review only adds events. Greedy 90-second packing leaves a short final part.

# Constraints
Generic rules, no anime/time-specific edits, no cut quota. Preserve previous exports, source audio and speech handles. Existing $0.10 per-attempt accounting and paid-response guards remain.

# Implementation
1. Require explicit reasons for omitted source units; narrow preservation to essential visual causes/reactions and honor validated selection in planner.
2. Allow validated global redundancy exclusions with dependency and uncertain-event protection.
3. Balance part durations around remaining material while preferring complete replies and enforcing 90 seconds. If actual replies require another part, repack rather than leaving a short tail. Review silent pauses from .75 seconds (previously eight), in <=2-second units with three actual views, before/after context, neighboring retained replies and matching speech handles. Evaluate narrative/emotional function rather than speech, motion or particular example objects.
4. Run regression/full checks and a separate source replay/export with comparative QA.

# Validation
Intentional redundant dialogue stays omitted, needed questions/prefixes and selected actions stay retained; malformed decisions fall back safely. Global dependencies rescue necessary context. Continuous/sparse dialogue and multiple cut intervals produce balanced parts without duplicate source or chopped words. Actual source output/cost/intro/action checks.

# Risks and rollback
Editorial judgments remain imperfect; preserve on uncertain evidence, require explicit partition/reasons, no artificial retained-duration target. New version signatures invalidate only affected choices. Existing runs remain independently playable.

# Progress
- [x] Confirm real regression and root causes.
- [x] Implement selection/global retention and balanced splitting.
- [x] Run regressions and full checks: 312 Python / 14 UI checks passed.
- [x] Render/verify separate result e6726f9f: 16 parts, all decoded and contact sheets inspected; 31 audio comparisons, zero best lag. See qa/final-validation.json.
- [x] Sync documentation and record the actual limits.
- [ ] Editorial acceptance: 22:30 of 23:40 remains too conservative; commentary remains in part 16. Pacing8's abstract narrative/emotional criterion is implemented/tested but not reexported. Technical success does not close these quality issues.
