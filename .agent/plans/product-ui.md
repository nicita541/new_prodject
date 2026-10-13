# Goal
Make Studio a product interface with Projects and Trash as global navigation, contextual episode workflows, and no developer API console.

# Current state
Studio's single HTML/JS/CSS interface exposes every contextual screen in the sidebar and retains an API request form, raw JSON actions and developer copy. Existing project/episode actions already provide contextual navigation. Another agent owns the new social frame; its frontend additions must be preserved.

# Constraints
Work in the current branch without committing or changing main. No backend changes, real montage/model runs or server stops. Preserve real errors, progress, provider choices, manual Antigravity and editing/export controls. All artifacts stay in the workspace.

# Implementation
1. Remove API screen, request log state, handlers and styles; simplify sidebar and technical copy.
2. Keep episode settings, processing, review and finishing accessible from the selected project/episode with breadcrumbs and contextual links.
3. Update regression checks to enforce product navigation and absence of developer controls.

# Validation
Run frontend npm test/lint/build and focused production-entrypoint tests. Exercise available local browser flows without launching processing.

# Risks and rollback
Old direct links to the removed API screen return to Projects. Preserve the product screen whitelist and context validation. Revert the scoped frontend/test diff if navigation regresses.

# Progress
- [x] Read guidance and inspect existing navigation and API UI.
- [x] Implement product navigation and remove developer UI, API handlers/state and styles.
- [x] Verify npm test/lint/build and contextual project/episode/review/finishing navigation against existing backend in browser without launching video/models.
- [x] Focused production-entrypoint tests: 6 passed after final wording refinement; frontend ownership released to social frame agent.
- [x] Integration removed remaining synthetic finishing metadata and added latest-attempt navigation/active context guards. Combined Python suite 1434 passed; current Studio DOM/lint/build passed.
