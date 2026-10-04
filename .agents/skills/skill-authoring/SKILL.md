---
name: skill-authoring
description: Use when a repository has a repeated, specialized, error-prone workflow that deserves its own agent skill. Create a focused skill with clear triggering metadata, concise instructions, optional references/scripts, and a verification step.
---

# Skill authoring

Create a skill only for a repeatable specialized workflow.

Requirements:
- one folder directly under `.agents/skills/`;
- folder name lowercase with hyphens;
- `SKILL.md` with matching `name`;
- a specific `description` explaining both what it does and when to use it;
- concise workflow instructions;
- optional `references/`, `scripts/`, or `assets/` only when useful;
- explicit verification/stop conditions where relevant.

Avoid duplicating generic model capabilities or creating several overlapping micro-skills.

