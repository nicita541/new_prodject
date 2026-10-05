# ADR-0017: Variable part lengths and sequence pacing

## Status
Accepted — 2026-10-05. Editorial acceptance remains source-dependent.

## Context
The 90-second ceiling and arithmetic balancing split conversations near 87 seconds even when a later complete beat would fit a 110-second clip. Independent two-second silent rows over-protected repeated travel as atmosphere and produced holes inside a continuous view.

## Decision
Use whole speech-free shot spans and review long silent sequences across artificial analysis windows. Keep confirmed story/action ranges and bounded speech handles; remove only explicitly evidenced neutral routine/repetition. Current neutral-view decisions supersede tentative atmosphere labels on those exact source ranges.

`app.endings` reviews the whole 90-second neighborhood around soft output-time targets in chronological pages of at most twelve source-boundary IDs. Keeping only the closest twelve IDs discarded completed beats farther from the target during whole-episode validation. Each ID carries exact preceding/following retained dialogue. A moderately confident proposal can trigger an independent local-dialogue check, but final authority requires confidence >=0.9 and matching last/next reply IDs. Reasons based on a future answer/payoff are rejected. Evidence is optional additive `part_endings` event metadata. Separately versioned checkpoints and final-event signatures preserve existing story/source facts and previous jobs.

If the resulting plan still has unsupported nonfinal boundaries, independently assess every alternative in that actual part's 60–120-second range in the same bounded pages. This recovery does not depend on the proposal model nominating the correct response, and can classify a completed setup before a new scene as a deliberate cliffhanger. It has a separate cache/recovery version, requires the same exact dialogue IDs and >=0.9 confidence, and preserves explicit fallback when evidence remains insufficient.

The planner chooses a chronological path on retained output time, favoring verified closures/cliffhangers over equal durations. 90 seconds is a soft target; 120 seconds is a processing ceiling, not a platform policy. Complete short replies cannot be split to fill a part. ASR tails near a source gap snap to the complete selected handle so no orphan audio starts the next part. Unsupported boundaries remain explicit warnings. Media validation and audit share the same ceiling.

## Alternatives considered
Raising the ceiling alone still selects arbitrary reply ends. Treating every shot change as closure can interrupt questions, jokes or actions. Source-specific exclusions and fixed removal quotas cannot generalize. One global boundary list confused IDs and attached later dialogue to earlier times; bounded candidate neighborhoods avoid that observed failure.

## Consequences
Old plan schema remains readable; new planner fingerprints rebuild exports when requested. Ending and sequence checks add provider work but reuse validated matching checkpoints. Text/ASR and visual summaries can miss silent payoffs; source/output review remains necessary. Diagnostic previews preserve prior jobs and distinguish checked samples from whole-episode exports.

## Revisit when
The processing ceiling prevents completing a needed beat, or unseen sources show recurring missed visual payoffs/over-retention.
