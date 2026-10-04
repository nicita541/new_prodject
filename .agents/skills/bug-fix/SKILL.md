---
name: bug-fix
description: Use when behavior is broken, inconsistent, regressed, or differs from the expected result. Reproduce the symptom, identify the root cause, make the smallest safe fix, add regression protection when useful, and verify nearby behavior.
---

# Bug fix

1. Reproduce or precisely characterize the failure.
2. Capture the actual failing path, state, logs, or conditions.
3. Narrow the cause before changing code.
4. Form and test a concrete root-cause hypothesis.
5. Make the smallest fix that addresses that cause.
6. Add a regression test/check when practical and valuable.
7. Re-run focused checks plus nearby affected behavior.
8. Inspect the final diff for speculative or unrelated edits.

Do not stack random fixes until the symptom disappears.

