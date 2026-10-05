# Goal
Completely redesign the UI from scratch to provide a modern, professional, "product-like" experience for a video editor (Кадр Studio). The redesign must not rely on the old HTML/CSS layout, but it must preserve existing JS business logic (by maintaining element IDs and event bindings). 

# Current state
The app relies on plain HTML (`app/static/index.html`), CSS (`style.css`), and Vanilla JS (`app.js`, `library.js`). The current layout was a standard dashboard with a topbar. A recent partial modification introduced a sidebar and NLE (Non-Linear Editor) layout, but the user requested a **complete from-scratch redesign** of all screens, components, and animations.

# Constraints
- Keep the pure HTML/CSS/JS stack without build tools (no React, Vue, Webpack, Node.js).
- Maintain existing `id` attributes in HTML so `app.js` and `library.js` continue to function without major rewrites.
- Ensure the NLE timeline logic (`#timeline-panel`, `#timeline-map`, etc.) remains functional and visible.
- Ensure all screens (Projects, Trash, Episodes, Edit, Review) are fully redesigned and styled.

# Implementation
1. **Design System & Base CSS (`style.css`)**: 
   - Wipe `style.css` and define new CSS variables (dark theme, modern indigo/cyan accents, soft typography, glassmorphism tokens).
   - Create generic component classes: `.btn-primary`, `.btn-secondary`, `.card`, `.input-text`, `.badge`.
2. **Global Layout (`index.html`)**:
   - Rewrite the outer shell of `index.html`. Establish a true Sidebar layout with a beautiful navigation menu.
3. **Screens Redesign (`index.html`)**:
   - `projects-screen` & `trash-screen`: Grid layout for anime projects with beautiful cards, hovering effects.
   - `episodes-screen`: List/grid of episodes with modern creation forms.
   - `edit-screen`: Wizard-like or structured 2-column settings layout with modern switches, sliders, and selects.
   - `review-screen`: A professional video editor interface (Source monitor, Program monitor, Timeline at bottom).
4. **JS Adjustments (`app.js`, `library.js`)**:
   - If any HTML structure changes require JS updates (e.g., changing how active nav items are highlighted or how elements are toggled), update them.
5. **Polishing**:
   - Add animations (fade-ins, smooth transitions).
   - Custom scrollbars.
   - Responsive design (collapsible sidebar for small screens).

# Validation
- The application loads successfully in the browser.
- Creating projects, episodes, and running the pipeline works.
- The UI looks professional and cohesive.
- The timeline and video players render correctly.

# Risks and rollback
- Risk: Breaking JS logic due to missing IDs or deeply coupled HTML structures (e.g., `.stages` or `.timeline-piece`).
- Rollback: Revert `index.html`, `style.css`, `app.js`, and `library.js` via git.

# Progress
- [ ] Define Design System in `style.css`.
- [ ] Rebuild Layout & Shell.
- [ ] Rebuild Projects & Trash Screens.
- [ ] Rebuild Edit Screen (Settings).
- [ ] Rebuild Review Screen (Timeline/NLE).
- [ ] Verify JS bindings and interactions.
