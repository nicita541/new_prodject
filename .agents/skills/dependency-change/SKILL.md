---
name: dependency-change
description: Use when adding, upgrading, replacing, or removing a package, SDK, plugin, framework, runtime, or other external dependency. Justify the dependency, review compatibility and security implications, make the smallest change, and verify the project afterward.
---

# Dependency change

1. Check whether the existing platform/dependencies already solve the need.
2. Confirm the package is maintained and appropriate for the project's license/platform constraints.
3. Review breaking changes and migration notes for upgrades.
4. Keep version/config changes minimal and intentional.
5. Update lockfiles using the project's normal tooling.
6. Run build/tests plus behavior that exercises the dependency.
7. Remove obsolete dependency/configuration when replacing a package.
8. Never introduce credentials into dependency configuration.

