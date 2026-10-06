# Architecture Decision Records

- [0018: Universal montage pipeline and smart audio ducking](0018-universal-pipeline-and-smart-audio.md) — multimodal full-episode OP/ED scanning, eyecatch removal, and dynamic Content ID audio ducking.

- [0017: Variable part lengths and sequence pacing](0017-variable-parts-and-sequence-pacing.md) — 70–120s parts anchored to narrative endings and verified cliffhangers.

- [0016: Derived plan diagnostics for review](0016-plan-review-diagnostics.md) — filtered to final retained intervals; no new endpoint.

- [0015: Direct requests without monetary launch gates](0015-simple-provider-retries.md) — current contract; supersedes monetary gating in earlier records.

- [0014: Bounded retries for confirmed response rejection](0014-confirmed-schema-correction.md)


Create an ADR only for a durable decision whose rationale would otherwise be lost.

Use filenames such as:

`0001-use-sqlite-for-local-cache.md`

Template:

```markdown
# ADR-0001: Decision title

## Status
Accepted | Superseded | Deprecated

## Context
What problem or constraint required a decision?

## Decision
What was chosen?

## Alternatives considered
What realistic alternatives were considered?

## Consequences
What becomes easier, harder, or constrained?

## Revisit when
What condition should trigger reconsideration?
```
