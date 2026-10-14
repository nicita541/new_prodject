# Goal

Implement the user's explicit choice to build from confirmed fragments while excluding uncertain material and preserving required source dependencies. Avoid another whole-source reassessment. Explain actual failures without mixing source-selection and relation counts.

# Current state

The previous job really completed278 additional CURRENT review attempts;265 answers pass native validation but most have honest confidence below.9.84 source owners remain unresolved;150 in the UI also includes66 downstream-only failures. Strict production currently requires every event to pass, so rechecking alone did not unblock this source. Source-ready selections and their original native proofs remain available.

# Constraints

Opt-in per-job policy; old strict default stays compatible. Preserve full source events/relations in an immutable source-qualified local archive before a working projection. Never raise confidence, forge accepted status, change original raw answers, drop dependency metadata, or let the planner restore omitted uncertain material. Only surviving source-ready material may reach existing relation/end/continuity checks. No inference during tests/preflight. After one authorized launch, do not monitor.

# Implementation

1. Add a local confirmed-fragment projection with explicit omission audit and fixed-point dependency closure. Remove dependent consumers and broken mandatory dialogue pairs rather than deleting requirements.
2. Apply projection before final quality/model recovery. Preserve scope across native recovery; if bounded checks stall, prune only implicated active owners and close dependencies again. Empty result is an honest actionable failure.
3. Keep strict native final gates and export validation. Record scope on the actual plan. Keep the full-source archive and original checkpoints for reversal.
4. Separate downstream-only failures from source counts and use an accurate stopping explanation.
5. Verify projection/dependencies, default compatibility, nearby pipeline tests, source-qualified real offline scope and preserved completed-stage identities. Apply the explicit user policy to this job, restart and launch once.

# Validation

No model provider in projection. Regression tests cover unresolved source omission, intact required chains, transitive consumers, bidirectional question/answer coverage, full-source immutability, retained downstream failures, stalled-owner pruning and no fabricated acceptance. Run established focused quality/selection/continuation suites. Native real-data offline scope must contain only unchanged ready proofs and satisfy existing prerequisite identity rules.

# Risks and rollback

Output can be substantially shorter. Source-ready material may still fail necessary relation/ending/continuity checks; do not promise model accuracy or export completion. If no independent confirmed material remains, report that explicitly. Disable the per-job policy to restore strict behavior; full events/relations and original checkpoints remain archived. Revert backed-up sources only with Studio idle.

# Progress

- [x] Actual failure audited and user preference answered.
- [ ] Projection and integration.
- [ ] Tests and offline source audit.
- [ ] Apply policy and launch without monitoring.
