---
name: multi-agent-execution
description: Use when a substantial task has independent workstreams that can be delegated without conflicting edits, such as separate modules, test analysis, documentation, or review. Define bounded scopes, use isolated branches/worktrees when needed, and integrate through one coordinator.
---

# Multi-agent execution

Use multiple agents only when parallelism adds value.

For each delegated workstream specify:
- objective;
- exact scope/ownership;
- constraints;
- expected output;
- validation.

Avoid parallel edits to the same files.
Use separate branches/worktrees for independent implementation when supported.
The coordinating agent owns integration, resolves conflicts, reruns combined verification, and gives the final completion claim.
Do not delegate a tiny task just to create more agents.

