---
name: repository-onboarding
description: Use when starting work in an unfamiliar repository or when the task touches an area whose structure, build flow, or ownership is unclear. Inspect only the relevant parts of the repo and identify entry points, conventions, validation commands, and likely side effects before editing.
---

# Repository onboarding

1. Start from the user's task, not from a full-repository crawl.
2. Inspect the nearest relevant files, entry points, build/config files, and existing tests.
3. Trace enough callers/callees to understand ownership and side effects.
4. Discover real build/test/lint commands from repository files; do not invent commands.
5. Note existing conventions and generated/vendor boundaries.
6. Summarize the safest edit surface, then proceed.

Avoid reading unrelated directories or large docs unless the task actually depends on them.

