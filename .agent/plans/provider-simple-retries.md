# Direct provider requests, no monetary launch gate

## Goal
The user can start/retry montage from the episode page. A provider request gets one attempt and at most two retries. Local money estimates, reservations, balance polling and historical unknown billing cannot block work.

## Current state
The previous runtime and browser independently required a positive locally recorded balance; a transport interruption halted every later episode. The user explicitly removed monetary accounting on 2026-10-05. Earlier accounting requirements are superseded. Existing OP/context fixes remain.

## Constraints
All work stays in F:/new_prodject. Preserve historical files unchanged. Keep key redaction, TLS/redirect protections, cancellation, strict JSON/source IDs, successful-response caching and bounded image/context sizes. Subagents reached the account usage limit; coordinator completes the blocking integration.

## Implementation
1. Replace the provider's accounting path with direct cached requests and a maximum of three sends.
2. Remove monetary gates from job creation/retry and browser controls; connection checking uses models only.
3. Replace obsolete billing-gate tests with retry/caching/cancellation/no-accounting regressions; test API/job integration.
4. Restart only the owned idle application server, verify the visible episode start control and launch through the normal interface.

## Validation
Run focused and full discovered unittest suites. Verify cached answers and failed calls do not modify historical spending files. Check actual API status and browser launch control; do not claim a completed new video until exported.

## Risks and rollback
Provider attempts may each be billed; user explicitly authorized two retries and removed local money tracking. Authentication and certificate errors fail immediately; cancellation never retries. Restore the prior Git version to roll back; historical accounting data remains available.

## Progress
- [x] User requirements and migration contract recorded.
- [x] Provider and launch gates implemented.
- [ ] Tests and browser integration verified.
- [ ] Git checkpoint and user handoff.
