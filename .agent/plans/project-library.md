# Goal
Separate anime projects, episode subprojects, editing settings/processing, and review into distinct navigable screens. One episode owns one source; attempts remain within that episode.

# Current state
The studio displays media, job, timeline and Shorts together. Jobs and sources persist independently without anime/episode ownership. Existing exports and billing must survive.

# Constraints
Keep files in the workspace; no dependencies or paid processing for migration/verification. Preserve job endpoints and UUID directories, source streaming, timeline and continuous playback. Use existing loopback protections and manager mutex.

# Implementation
1. Add a small versioned catalog for anime/episode identity, source binding, saved settings and legacy job associations. Derive job states from existing jobs. Migrate legacy jobs idempotently by registered source and parsed title/episode number; retain every output.
2. Add validated catalog APIs and episode-bound job creation. Preserve old API callers. Save episode identity before worker startup, so interrupted launches remain associated.
3. Present project library, anime episode list, episode settings/processing and review as separate hash routes. Back/breadcrumb navigation, saved settings, scoped attempt selector. No global history in editing/review. Keep timeline and players on review only.
4. Verify catalog persistence/isolation/migration, API integration, UI routing and real browser navigation. Restart only the owned idle server to load APIs, without paid processing. Sync docs.
5. Add requested project/episode deletion controls and a recoverable trash route. Archive only catalog records; preserve exports/accounting and block active episode/parent deletion. Validate restore conflicts.

# Validation
Focused Python API/catalog tests; existing Node UI suite plus routing checks; actual existing episode review and settings navigation; new project/episode creation and persistence. Responsive screenshot.

# Risks and rollback
Legacy filename inference can be uncertain: preserve source identity, never overwrite jobs or infer media content. Catalog is additive data/library.json and can be backed up; removing it leaves original jobs and media intact. One source cannot silently replace another inside an episode. Legacy APIs remain usable.

# Progress
- [x] Catalog and migration
- [x] APIs and episode-bound jobs
- [x] Separate screens and navigation
- [x] Project/episode deletion and recovery
- [x] Tests/browser/docs

## Verification, 3 October 2026
Full unittest discovery: 280 tests passed in 18.479 s; focused API: 25 passed. Node UI suite: 14 passed after the final notice routing fix. API tests cover catalog persistence, legacy output preservation, source isolation, new job ownership, input/origin guards, archive/reload, parent restoration retaining individually archived children, legacy/new active deletion blocks and restore conflicts. UI tests cover separate/scoped routes, free settings save vs episode launch, completion navigation, trash/restore and continuing source playback.

Owned idle loopback server restarted with trash APIs (PID 2660). Real browser navigated projects → series → settings → review; settings saved without launch. The existing series and parent project were separately archived and immediately restored through the UI; catalog is back to one project/one episode, no archived entries, two retained attempts and 13 final parts. Private ledger SHA256 remained AA92B5FEC3767EAC734A1ED983E37DAB006275BB6F81038BD5C4A30B9B5B2A45. No paid processing was launched.

1440 px desktop and 380 px narrow screens verified; narrow document width equals 380, one active screen. Temporary viewport reset. Screenshots in root qa/library-projects.jpg, library-episodes.jpg, library-review.jpg and library-trash.jpg. Previous media quality limitations remain in docs/quality-audit.md.

Final user adjustment removes the “Из чего состоит часть” list entirely. Part selection now highlights its bracket on the single timeline and selects the corresponding Short; kept/removed source clicks still play their intervals. Removed list render logic/styles and updated the timeline regression test; all 14 UI checks passed again. Review screenshot refreshed after removal.
