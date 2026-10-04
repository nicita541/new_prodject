# ExecPlans

Use an ExecPlan for work that is genuinely complex: cross-cutting features, architectural changes, migrations, significant refactors, or work likely to span several dependent implementation stages.

Do **not** create an ExecPlan for a typo, tiny localized bug, simple content change, or another task that can be safely completed and verified directly.

## Location
Create active plans under `.agent/plans/` with a descriptive filename, for example:

` .agent/plans/save-system-refactor.md `

## Required sections

### Goal
Describe the user-visible or system outcome.

### Current state
Summarize only the repository facts needed to understand the change.

### Constraints
List compatibility, platform, data, security, release, or architectural constraints.

### Implementation
Use ordered milestones. Each milestone should leave the repository in a coherent state when practical.

### Validation
List the concrete build/tests/checks or manual flows that demonstrate success.

### Risks and rollback
State meaningful risks and how to reverse or contain the change.

### Progress
Keep a short checklist for long-running work. Update it as implementation proceeds.

An ExecPlan is a working implementation document, not a speculative essay. Revise it when repository evidence invalidates an assumption.
