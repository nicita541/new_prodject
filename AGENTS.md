# Repository agent guidance

Keep this file short. It applies broadly; detailed workflows belong in `.agents/skills/`.

## Working rules
- Work in `F:\new_prodject`. Keep all task-related installations, dependencies, environments, downloads, caches, and generated files inside this folder; do not install globally or write to other drives. If a tool cannot comply, explain the constraint and obtain user approval before proceeding.
- Follow existing repository conventions and preserve behavior unless the task explicitly changes it.
- Inspect only the code and documentation relevant to the current task; do not crawl the whole repository by default.
- Discover build/test/lint commands from the repository instead of inventing them.
- Use the relevant skill in `.agents/skills/` when its description matches the task. Do not preload or chain every skill.
- For complex features, architectural changes, migrations, or significant refactors, use an ExecPlan as defined in `.agent/PLANS.md`. Do not create an ExecPlan for trivial work.
- Never claim a build, test, check, or manual flow passed unless it was actually run.
- Keep secrets, tokens, passwords, private keys, signing credentials, and sensitive values out of source control and logs.
- Prefer small, reviewable, reversible changes over broad rewrites.

## Project documentation
Read these only when relevant:
- `docs/ai/architecture.md` — component boundaries and stable data flow.
- `docs/ai/project-context.md` — non-obvious stable project/tooling facts.
- `docs/ai/known-issues.md` — unresolved known issues.
- `docs/ai/decisions/` — durable architectural/tooling decisions.

Update these documents only when durable project knowledge changes. Git history is the record of routine edits.
