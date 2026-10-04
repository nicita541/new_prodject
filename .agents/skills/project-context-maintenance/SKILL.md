---
name: project-context-maintenance
description: Use when work reveals durable project knowledge that future agents would otherwise have to rediscover: stable architecture facts, non-obvious conventions, recurring environment constraints, known unresolved issues, or important technical decisions. Keep project context concise and current.
---

# Project context maintenance

Store only durable, cross-task information.

Use:
- `docs/ai/project-context.md` for stable environment/build facts and non-obvious conventions;
- `docs/ai/known-issues.md` for unresolved, reproducible project issues;
- `docs/ai/architecture.md` for stable component boundaries/data flow;
- `docs/ai/decisions/` for important architectural/tooling decisions.

Do not record routine diffs, temporary debugging notes, chat history, or facts already obvious from code.
Delete or correct stale context when discovered.

