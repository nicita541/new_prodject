# Stabilization after KADR Studio full audit (2026-10-10)

## Goal
Restore reliable caption editing and finishing in the *actual production Studio Edition* and React editor; then address preservation of exports, music and scene quality. No original MP4, source material, or previous saved drafts may be silently overwritten.

## Current state
- Current branch: `codex/dramatic-montage`, starting HEAD `b28407dea466`.
- The episode-level finishing profile has `part_overrides.{index}.cues`, while each montage job also has independent `finishing/captions_NNN.json`. This creates cross-job confusion and conflicts between editor/FFmpeg.
- The previous fixes changed timed browser caption visibility without ensuring actual job-scoped caption ownership.
- Production Studio is `frontend/public/studio-edition-app.js` through `studio-live-bridge.js`, not the React route alone.
- CI is Linux-only and selects a subset of existing Python suites; editorial acceptance and Windows-specific file/FFmpeg behavior require local validation.

## Constraints
- Work only in `codex/dramatic-montage`; do not edit `main`.
- Do not delete existing user files or silently migrate ambiguous legacy caption overrides onto a different job.
- Preserve episode-scoped styling and job-scoped text and timing; exported MP4/SRT must use the same validated job's captions as the editing UI.
- Respect revision conflicts; reject invalid timing before rendering.
- Avoid DeepSeek/model calls in automatic regression tests. Run Windows smoke on the user's machine before declaring release ready.
- Commit each milestone separately and wait for CI before marking verified.

## Implementation
1. **Caption ownership and source-of-truth (P0/P1).** Make job-specific saved captions authoritative for editing and rendering; do not use episode-level stale cue text for another job. Keep old profile data intact as legacy backup and introduce regression tests for two completed attempts of one episode, edited text, and repeated export.
2. **Safe saving and validation (P1).** Prevent conflicting profile writes and partial/confusing saves; validate draft cues for the real part duration. Make reset semantics explicit and nondestructive; test 409/422 and multi-window behavior.
3. **Preview parity and usability (P1).** Align paused editing vs playback; show subtitle enabled toggle in production Studio; clarify already-burned subtitles in browser preview; ensure server MP4 preview uses correct edited cues, style and zoom. Add end-to-end FFmpeg video tests.
4. **Background exports and music (P1/P2).** Bound finishing worker queue, protect active exports from job cleanup and other launch races, restore/mark interrupts clearly, fix track absence and no-music choices; run concurrent-job tests.
5. **Library, launch and coverage (P2).** Verify Trash/restore, archives, cached plans, Windows filenames, startup identity, media downloads; expand CI targeted suites and add real Studio browser tests for editing.
6. **Narrative quality (separate acceptance).** Inspect fresh real series with permission, diagnose microcuts, bridge action, missing questions/replies and unfinished speech; compare source timeline and exports. Do not call model quality proven from synthetic fixtures.

## Validation
- `python -m pytest -q tests/test_finishing.py tests/test_jobs.py tests/test_media.py tests/test_subtitles.py`
- `node frontend/scripts/smoke-studio-exact.mjs` and `node frontend/scripts/smoke-studio-bridge.mjs`
- `cd frontend && npm test -- --run && npm run lint && npm run build` (use commands shown in CI/package.json for exact flags)
- GitHub Actions production checks on every commit.
- Windows: `ПРОВЕРИТЬ_ПРОЕКТ.bat -Quick`, then `-Video` (with portable FFmpeg), plus a manually reviewed completed job and source-relative captions.
- Confirm old untouched plans, originals, MP4 and profile backups have not been rewritten.

## Risks and rollback
- Legacy episode-level cue overrides have no job identity. Never silently assign them to all jobs; retain original on disk for explicit repair later.
- Browser overlay is not proof of FFmpeg output: a finished MP4 can already have burned subtitles.
- Async render and job cleanup lock ordering must not deadlock. Limit scope and run interruption tests.
- Roll back each small commit by revert on the branch only, after protecting new user drafts and backups; do not force reset local Windows workspace.

## Progress
- [x] Re-read actual caption data flow, current CI and past regression commits.
- [x] Publish this execution plan.
- [x] Milestone 1: job-scoped captions in API, Studio Edition, React and FFmpeg; archive ambiguous legacy episode cues; add regression tests. Commits 9683bd89, 4a9d2c84, d2d87ada, c9fa6c4a, 3280ec8e, 417f7fce.
- [x] Milestone 2: profile optimistic revisions, joint preflight of changed captions and style, rollback on ordinary disk write errors, job-scoped original-caption retention, and explicit style-only reset are implemented. Commits include 20e3dad7, bd5149c5, 754cf353. Multi-file writes are NOT crash-atomic; crash-recovery journaling is a future hardening task.
- [x] Milestone 3 code + Linux test: enabled toggle, baked-caption preview isolation and actual 1080×1920 FFmpeg finishing smoke (edited job cue, zoom=90%, music). Windows visual parity is still a local acceptance check.
- [x] Milestone 4 code: queue limited to three, track existence and no-music, new analysis gated during export, stale export indices removed, and cancellation plus bounded join of FFmpeg workers on shutdown (201c0cb0). Persisted unfinished tasks are explicitly marked interrupted on subsequent reads; automatic resumption across process restart is intentionally NOT implemented.
- [ ] Milestone 5: PARTIAL — expanded semantic/recovery tests and added automated three-minute real-media technical E2E with FFmpeg, music, subtitles, preview, validated cache, deliberate SRT corruption, rerender and machine-readable logs (9e5de434, ee183370). Linux pipeline passed at GitHub run 38024938885; actual Windows and library UX acceptance are pending.
- [ ] Milestone 6: added `--mode real` path running true local ASR/VLM and source-grounded quality gate with a fresh three-minute story video, followed by a second model/cache integrity run. Execution requires user's local models, 180-second story clip and inspection of actual montage; cannot honestly mark passed from synthetic/Linux test.
