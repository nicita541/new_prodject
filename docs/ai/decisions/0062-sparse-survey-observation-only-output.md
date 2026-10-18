# ADR-0062: Keep sparse visual survey output limited to observations

Status: implemented, mechanism-tested and exercised through real full-route resume.

## Context

The fresh120s ordinary pipeline failed before any DeepSeek call: the second local
survey request exhausted2048 output tokens and returned incomplete JSON. It had
only two windows. Each observation already bounded its summary to240 characters,
but additionally requested an unbounded list of unbounded unanswered questions.
The full episode-map request subsequently generated questions again using the
complete catalog and exact ASR. Sparse frames cannot determine all prerequisites
or story completeness in isolation.

The exact malformed response was not retained, so its individual repeated fields
cannot be reconstructed. Length exhaustion and the unbounded schema are observed;
the benefit of simplifying this contract must be verified on real inference.

## Decision

Keep the local survey responsible for one factual summary and uncertainty flag
per window. Remove speculative question generation from its output schema/prompt.
The existing full episode-map stage continues to own hypotheses, prerequisites
and unanswered questions after seeing all observations and exact speech. No new
pass, output-budget increase, question-count cap or model fallback is added.

Keep every original window, owned frame, ASR row and explicit uncertainty.
An uncertain observation still has no selection/completeness authority. Existing
saved survey/map records containing questions remain readable; changed prompts,
schema and source-stage code identity distinguish new work. Old failed question
reservations and original responses are not rewritten or relabelled as successful.

## Validation and rollback

Focused survey/source/question/candidate/provider/pipeline suite:131tests and
36subtests passed. Regression checks reject speculative unbounded survey lists,
retain uncertain-window coverage and full exact ASR in map input, and preserve
warm reuse/unknown-dispatch behavior. Test model fixtures follow the new output
contract; legacy authored map records remain covered.

The failed actual run and code identity are archived separately from the ordinary
resume under benchmark/initial-failure. The resume is not a cold speed comparison.
Reverting the two survey-contract edits restores the previous wire shape; neither
version authorizes publishing an unproved story. Corpus/quality/audio acceptance
remains independent of JSON success.

The ordinary resume completed both local survey batches with228 and182 output
tokens, then reached actual story selection/render/publication. It exported one
50.13s clip with no technical failures; unchanged full-route warm reuse forbade
local startup and remote transport and made0new calls. These are one-source
mechanism/integration results, not proof of editorial quality or corpus recall.
