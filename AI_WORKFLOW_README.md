# Universal Agent Project Starter

Drop the contents of this archive into a repository root.

This version is intentionally lean:
- short root `AGENTS.md`;
- on-demand skills in the standard `.agents/skills/<name>/SKILL.md` layout;
- an ExecPlan convention for genuinely complex work;
- durable project context separated from Git history;
- no installer and no always-loaded giant memory file.

## Included skills (16)

- `repository-onboarding` — Use when starting work in an unfamiliar repository or when the task touches an area whose structure, build flow, or ownership is unclear. Inspect only the relevant parts of the repo and identify entry points, conventions, validation commands, and likely side effects before editing.
- `feature-development` — Use for implementing a new user-visible feature or capability that changes behavior across one or more files. Clarify acceptance criteria, choose the smallest compatible design, implement incrementally, and verify the complete user flow.
- `bug-fix` — Use when behavior is broken, inconsistent, regressed, or differs from the expected result. Reproduce the symptom, identify the root cause, make the smallest safe fix, add regression protection when useful, and verify nearby behavior.
- `build-failure-triage` — Use when a build, compilation, packaging, CI, signing, or release pipeline fails. Separate the first causal error from follow-on noise, reproduce locally when possible, fix the responsible configuration or code, and rerun the failing stage.
- `safe-refactor` — Use for restructuring, renaming, moving, deduplicating, or simplifying code while preserving externally observable behavior. Establish protection first, make reversible steps, keep the scope focused, and verify behavior after the refactor.
- `architecture-change` — Use when changing module boundaries, data flow, persistence, public interfaces, service ownership, or another long-lived architectural decision. Analyze dependencies and tradeoffs, create an ExecPlan, document the decision, and preserve migration/rollback paths.
- `test-strategy` — Use when deciding how to verify a feature, bug fix, refactor, or release, especially when the right balance of unit, integration, end-to-end, smoke, and manual checks is unclear. Design the smallest test set that protects important behavior.
- `code-review` — Use when reviewing a patch, branch, pull request, or completed implementation. Look for correctness and regressions first, then security, architecture, error handling, tests, performance, and maintainability. Report concrete findings with evidence.
- `security-review` — Use when code touches authentication, authorization, secrets, user-controlled input, file/network access, sensitive data, payments, external integrations, or another trust boundary. Review concrete attack paths and least-privilege assumptions.
- `dependency-change` — Use when adding, upgrading, replacing, or removing a package, SDK, plugin, framework, runtime, or other external dependency. Justify the dependency, review compatibility and security implications, make the smallest change, and verify the project afterward.
- `risky-change` — Use for migrations, destructive operations, large data/state changes, signing/release changes, production configuration changes, or any edit with a wide blast radius or difficult rollback. Analyze impact first and define rollback and validation before execution.
- `release-readiness` — Use when preparing a build or repository state for a real release, deployment, store submission, package publication, or handoff. Validate versioning, build/tests, configuration, secrets/signing, migrations, artifacts, release notes, and rollback readiness.
- `documentation-sync` — Use after code changes that alter setup, commands, configuration, public APIs, architecture, deployment, or user-visible behavior. Update only documentation that became inaccurate or incomplete, and remove stale contradictory instructions.
- `multi-agent-execution` — Use when a substantial task has independent workstreams that can be delegated without conflicting edits, such as separate modules, test analysis, documentation, or review. Define bounded scopes, use isolated branches/worktrees when needed, and integrate through one coordinator.
- `project-context-maintenance` — Use when work reveals durable project knowledge that future agents would otherwise have to rediscover: stable architecture facts, non-obvious conventions, recurring environment constraints, known unresolved issues, or important technical decisions. Keep project context concise and current.
- `skill-authoring` — Use when a repository has a repeated, specialized, error-prone workflow that deserves its own agent skill. Create a focused skill with clear triggering metadata, concise instructions, optional references/scripts, and a verification step.

## Structure

```text
project/
├─ AGENTS.md
├─ .agents/
│  └─ skills/
│     ├─ bug-fix/
│     │  └─ SKILL.md
│     └─ ...
├─ .agent/
│  ├─ PLANS.md
│  └─ plans/
└─ docs/
   └─ ai/
      ├─ architecture.md
      ├─ project-context.md
      ├─ known-issues.md
      └─ decisions/
         └─ README.md
```

## Important

If the target repository already has an `AGENTS.md`, merge the useful rules instead of blindly overwriting it.

The skill directory layout is intentionally flat. Many agent implementations discover project skills as direct children of `.agents/skills/`.
