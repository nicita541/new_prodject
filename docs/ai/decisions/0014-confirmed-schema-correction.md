# ADR-0014: Bounded retries for confirmed response rejection

Current status: superseded for active runtime by [ADR-0015](0015-simple-provider-retries.md), 2026-10-05. This record describes historical accounting/recovery behavior, not the current launch contract.

## Status

Accepted for confirmed response rejections and the exact third-run unknown seed; extended network-uncertainty authorization recorded, implementation pending. Direct user instructions are preserved in [the montage quality specification](../../specs/montage-quality.md). The current selected two-retry policy and the exact third-run seed are active. The fourth Marie run failed before planning with a separate transport-unknown request; its recovery is pending the bounded policy extension and a reviewed exact-snapshot helper.

## Context

A paid structured response can be valid JSON yet fail its exact schema when the model treats supplied enum IDs as examples or lets labels visible in contextual frames expand the requested set. The user wrote `разреши повторять 2 рага на каждый запрос,` (verbatim); from context, `рага` is interpreted as `раза`, authorizing at most two retries per request family and three chat attempts total. The user later also wrote `Да, два повтора после сетевого сбоя с сохранением расходов` (verbatim), authorizing at most two retries following a post-send network failure while preserving the uncertain expense. Usage remains unconfirmed unless valid provider usage is present. Authentication, insufficient balance, certificate failures, malformed responses without trustworthy usage, cancellation, and unrelated errors are outside that authorization.

## Decision

Persist a workspace provider policy with at most two paid retries for every new montage request family. Missing or legacy policy defaults to zero. Snapshot the selected policy into each job and persist a retry count keyed by stable request-family evidence/model/schema identity; starting a new job or attempt must not reset it. The known Marie schema rejection counts as the initial attempt, so at most two more attempts may follow. Automatic content/schema retries require valid recorded usage within reservation. The later direct network-failure authorization permits a narrowly classified post-send transport uncertainty to be retained as an acknowledged unknown and retried only when both the persisted workspace policy and the current job snapshot opt in, the family cap is not exhausted, and no other unknown/reserved entries make the ledger unsafe. Keep the full reservation; never represent this as confirmed usage. Authentication, TLS/certificate verification, HTTP response errors, parse errors, insufficient balance, over-reservation, and cancellation before send are ineligible. Each attempt has its own identity and retained charge; the cap applies across all retry categories.

Recovery validates every ledger entry before reopening new work. Completed charges must match recorded nonnegative integer usage and remain within their reservation. An `acknowledged_unknown` entry is accepted only when its retained charge equals its original reservation and its request is already blocked; its status, charge, and replay block stay unchanged. Any new reserved, unknown, or unknown-usage entry still prevents recovery. Recovery checks a reviewed ledger snapshot hash under the spending lock before balance I/O or any write.

Retry prompt guidance clarifies that schema enums are exhaustive allowed values and other visible labels are evidence only. The original schema and image pages stay fixed. Successful output ends the chain and is cached; later matching calls reuse it without another charge. Every failed attempt remains recorded and blocked. The counter survives process restart and cache replay, so changing wording or starting a new job cannot reset the per-family limit. The existing two older acknowledged unknown charges remain charged and blocked. The exact third-run Marie unknown was separately authorized to retain its reservation and consume attempt one. The fourth-run network-unknown remains blocked until the new transport policy and an exact reviewed recovery helper are tested and activated. No earlier unknown history receives retry authorization by implication.

## Alternatives considered

- Clear the account halt or remove historical blocked digests: rejected because that would allow paid requests to replay.
- Treat acknowledged unknown charges as completed usage: rejected because their token usage remains unverified.
- Retry after post-send network uncertainty: initially rejected because a second chat may duplicate a charge whose first result is unknown; the user later explicitly authorized up to two retries while retaining the original expense, with strict category, family-cap, and ledger-eligibility guards.
- Add an unbounded retry loop or reset the counter on a new job: rejected because user authorization caps the same request family at two retries.

## Consequences

Retry state is narrow, durable ledger data. Every completed usage entry stays charged; eligible network-uncertain requests keep their full retained reservation and do not claim confirmed usage. Ineligible unknown requests halt recovery. Existing acknowledged reservations remain blocked and charged unless a separate exact user authorization and guarded migration applies. Existing ledger entries are preserved without broad migration. Reverting code leaves the charge history intact; never roll back or edit the ledger to undo a paid attempt.

## Revisit when

Revisit only if provider accounting guarantees, request-family identity, or the user's retry allowance changes. Any broader retry count needs separate explicit approval and regression coverage for charge retention, unknown requests, cache reuse, restart, cancellation, and concurrent access.
