---
name: architecture-change
description: Use when changing module boundaries, data flow, persistence, public interfaces, service ownership, or another long-lived architectural decision. Analyze dependencies and tradeoffs, create an ExecPlan, document the decision, and preserve migration/rollback paths.
---

# Architecture change

1. State the architectural problem and constraints.
2. Map affected modules, interfaces, data/state, external integrations, and reverse dependencies.
3. Compare viable approaches and choose the simplest design that meets the requirement.
4. Create/update an ExecPlan in `.agent/PLANS.md`.
5. Define compatibility, migration, observability, and rollback needs.
6. Implement in reviewable stages.
7. Verify integration boundaries, not only local units.
8. Add an ADR under `docs/ai/decisions/` for a durable decision.
9. Update `docs/ai/architecture.md` if the system structure actually changed.

