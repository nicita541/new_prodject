---
name: safe-refactor
description: Use for restructuring, renaming, moving, deduplicating, or simplifying code while preserving externally observable behavior. Establish protection first, make reversible steps, keep the scope focused, and verify behavior after the refactor.
---

# Safe refactor

1. Define which behavior must remain unchanged.
2. Inspect consumers and reverse dependencies of the code being changed.
3. Establish tests or repeatable checks before risky structural edits.
4. Refactor in small reversible steps.
5. Prefer clearer ownership and lower coupling over extra abstraction.
6. Avoid mixing unrelated feature work into the refactor.
7. Run focused and integration checks appropriate to the blast radius.
8. Remove temporary compatibility code only when all consumers have migrated.

