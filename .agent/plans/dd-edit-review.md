# Goal
Correct episode 1 exports: try for at most five Shorts, remove actual intro/title material, prevent audible speech truncation, and reuse valid analysis and unchanged exports.

# Current state
Recovered job 00a9e488-dbe1-4614-9ec1-cf443e26083e contains nine completed parts. Structured selections skipped speech margins. The old restricted Antigravity persona could not open images: print-mode @ mentions yielded media=0 and invented scenes. Original ASR and text-backed facts remain usable; visual replies lacking delivery evidence are not trusted. A five-part draft was incoherent. Reviewed complete-scene selection currently yields six parts and still needs final visual transitions.

# Constraints
Preserve source, ASR, existing validated replies and unrelated edits. Five is a soft preference; never satisfy it by cutting words or required story context. Targeted missing Google checks are authorized. All artifacts remain inside the workspace.

# Implementation
1. Audit existing cuts against source audio, exclusions, source proofs and available retention allocation.
2. Fix evidenced boundary and preference defects with focused regression checks.
3. Prepare a source-validated corrected plan, preserving prior exports as rollback.
4. Reuse unchanged rendering checkpoints, render changed parts and check resulting files and project status.

# Validation
Planner/retention/quality suites, source boundary samples, final source and plan gates, actual native media validation and completed project outputs.

# Risks and rollback
Speech handles must not restore omitted dialogue or excluded titles. Condensation can create missing context; native gates remain mandatory. Keep prior analysis/plan/output backups and immutable provider replies.

# Progress
- [x] Confirm existing completed result and user preference.
- [ ] Audit source audio/title and reduced-count plan.
- [x] Implement and test focused fixes (220 tests before the latest count refinement; latest focused suite 127 tests and 70 subtests).
- [ ] Validate corrected plan and export changed parts.
- [x] Verify actual image delivery and bind official visual imports to exact receipts; preserve text packet cache identities.
- [ ] Publish a separate corrected montage in the existing episode; preserve the nine-part job for comparison.

## Review snapshot published 2026-10-13
User explicitly requested immediate visibility even for unfinished edits, and asked to always publish intermediate versions in Studio. A separate playable draft job `499000c4-f0da-4c51-b4ee-e345dac2aa48` now belongs to episode `c7a3c833-36f5-401b-9c5a-6ce93ee4eae2`. Six parts, 621.591211 seconds. Native render_part validated all six MP4/SRT pairs; all six media HEAD requests returned 200. Actual Studio shows both the draft and original nine-part attempt, an explicit unfinished banner, and playback readyState 4 without media errors. Source ASR reused; original outputs untouched. The production gate remains unresolved for transitions 370.3–583.2 and 903.115–994.43; do not describe the draft as approved/final. Publish subsequent reviewable snapshots without waiting for editorial perfection.

Frontend build passed. Existing smoke suite still fails its previously observed caption disappearance assertion; live bridge smoke passes. Screenshot saved at temp/dd-recovery/draft-review-published.png (user is viewing the draft video full screen).
