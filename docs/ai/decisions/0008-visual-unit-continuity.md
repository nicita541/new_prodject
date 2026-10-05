# Preserve visual continuity within selected source units

## Decision
Condensation retains whole selected units bounded by actual replies/shots. Speech timing controls caption timing and word-safe part boundaries, not trimming of silent visual setup or reaction. Current source images are required for condensation even in dense dialogue; missing images preserve the event with a warning. Storyboards first cover every selectable source unit, then use supplementary shot/action samples (normally up to seventeen frames).

Production-title screening includes short silent runs and studio/distributor bumpers. Positive group screening alone cannot remove footage: each excluded unit needs independent current-image confirmation that the whole unit is nonnarrative, at the existing confidence threshold. Abstract animation adjoining a proven bumper needs a second joint image check that it belongs to the same bumper; there is no fixed time padding. In-scene signage and meaningful character dialogue/action remain protected.

## Alternatives
Increasing the model alone leaves word-margin trimming and the eight-second title eligibility rule unchanged. A universal time exclusion or an episode-specific opening interval cannot generalize. Keeping complete selected units is the smallest deterministic correction; visual pacing still evaluates long redundant waits separately.

## Compatibility and rollback
Analysis version 8 migrates versions 6/7 with the same source fingerprint and preserves factual probe/audio/transcript/shot artifacts. Visual/story decisions are invalidated by versioned signatures. Story version 6 and titles version 4 prevent stale choices being reused. Title verification additionally uses silent shot boundaries without the story-unit minimum duration, so a short bumper is not merged with later dialogue. Existing completed jobs stay available; validation uses a separate attempt. Reverting these changes rolls back future processing, while existing exports and cumulative accounting remain intact.

## Validation
Synthetic cases cover dense dialogue imagery, setup/reaction retention, missing imagery, short bumpers at shifted positions, signage/dialogue protection, and storyboard unit coverage. Real-source QA and complete exports are documented in the quality audit after execution.
