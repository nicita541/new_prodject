# UI layout and review controls repair

Source video used its intrinsic 1920px width inside a 904px review panel. Timeline markup used `.timeline-fragment` while styles targeted the older `.timeline-piece`, leaving the track black. The fixed sidebar and unwrapped controls also clipped the editor at narrow widths.

The source and result players now fit their panels. Retained, omitted and debug timeline intervals have matching styles; zoom scrolls locally. Responsive navigation, wrapping controls and shrinking grid/form columns keep five pages usable from 320px. The existing palette and typography remain.

Upload now handles advertised drag/drop and keyboard activation, validates successful responses and displays recoverable errors. Part-limit activation and part buttons establish source playback boundaries. Review distinguishes loading from an empty result and resets source timeline state on attempt changes. The editor links to an existing completed result even when a later attempt failed. The save label describes episode settings; the broken DeepSeek help link is replaced by inline configuration guidance.

The coordinator also added readable names and recognized progress groups for the production global verification and quality gate checkpoints. Two regressions cover their actual server stage keys.

Validation: **87 frontend tests across 20 files passed**, TypeScript/Vite build passed, lint exited 0 with **seven existing effect warnings**, and diff check passed. The built application at `http://127.0.0.1:8765` was inspected on projects, episodes, edit, completed review and trash at 1280, 820, 390 and 320px: **20 layouts passed** with no outside elements or captured browser console errors/warnings. Source/result play, pause, seek, playlist switching, zoom, analysis display and context copy were exercised in the actual browser. Existing episode settings were saved with unchanged values; no montage was launched.

Before/after screenshots, layout measurements and the full browser audit are in `scratch/ui-layout-repair/`. Upload failure and archive/restore contracts were checked with fixtures. Native folder-save dialogs were not manually exercised; existing API tests cover that contract. GPU inference and semantic pipeline code are separate from this UI repair.

During the subsequent real full-episode run, scene detection (`scenes`, progress .19/.21) appeared under preparation. Commit `87a0b7a` maps it to analysis and adds two regressions for the actual backend states. The updated snapshot passed **89 frontend tests**, TypeScript/Vite build and lint (zero errors, seven existing warnings). The running server served the rebuilt bundle with the corrected mapping. No new visual browser check is claimed: browser control surfaces were unavailable in that session.
