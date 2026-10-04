---
name: feature-development
description: Use for implementing a new user-visible feature or capability that changes behavior across one or more files. Clarify acceptance criteria, choose the smallest compatible design, implement incrementally, and verify the complete user flow.
---

# Feature development

1. Extract observable acceptance criteria from the request.
2. Inspect the existing path that most closely matches the feature.
3. Reuse established architecture and conventions unless they block the requirement.
4. For a complex or cross-cutting feature, create/update an ExecPlan using `.agent/PLANS.md`.
5. Implement in small coherent changes.
6. Add or update tests where they provide meaningful regression protection.
7. Run the relevant build/tests/static checks already used by the repository.
8. Exercise the changed flow when practical.
9. Update docs only when behavior, setup, API, or architecture actually changed.

