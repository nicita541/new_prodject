# Goal
Keep videos, timelines, forms and navigation inside the workspace, with usable desktop and narrow-screen controls.

# Current state
The React UI uses `frontend/src/styles/style.css`. Live review shows the 1920px source video inside a 904px panel; timeline JSX uses classes absent from the stylesheet. The fixed 240px sidebar leaves the mobile editor clipped. Upload advertises drag/drop and keyboard interaction without handlers.

# Constraints
Edit frontend only, preserve the flat library API and existing visual direction. Never start or cancel montage work. Keep runtime and screenshots in F:/new_prodject. Parent owns integration and commits.

# Implementation
1. Align CSS with rendered components and contain media/form intrinsic sizing.
2. Adapt navigation, grids and action rows to narrow screens.
3. Repair upload interaction and timeline selection/limit state where evidenced.

# Validation
Run existing frontend test, build and lint commands. Inspect real projects, episodes, editor, review and trash at desktop/tablet/mobile widths; record before/after screenshots and DOM overflow measurements.

# Risks and rollback
Responsive changes can affect desktop spacing. Retain palette and component structure; rollback scoped frontend changes if needed. Review media playback without starting rendering jobs.

# Progress
- [x] Reproduce live desktop source-video overflow, black timeline, and mobile clipping.
- [x] Implement contained responsive layout and interaction fixes.
- [x] Run checks and real browser audit: 85 tests pass; TypeScript/Vite build pass; lint exits 0 with seven existing effect warnings. Five production pages checked at 1280, 820, 390 and 320px with no outer horizontal overflow. Source/short play, seek, zoom, analysis, copy and unchanged settings save verified. Screenshots and metrics live under scratch/ui-layout-repair.
