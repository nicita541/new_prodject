---
name: test-strategy
description: Use when deciding how to verify a feature, bug fix, refactor, or release, especially when the right balance of unit, integration, end-to-end, smoke, and manual checks is unclear. Design the smallest test set that protects important behavior.
---

# Test strategy

Choose tests by risk and observability:
- unit tests for isolated logic;
- integration tests for boundaries and stateful interactions;
- end-to-end tests for critical user flows;
- smoke checks for packaging/deployment/startup;
- manual checks only where automation is impractical.

Prioritize regressions, edge cases, failure handling, and critical paths.
Do not add duplicate low-value tests merely to increase coverage.
Use the repository's existing test conventions and commands.

