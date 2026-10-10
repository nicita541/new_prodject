# Dedicated KADR testing menu and report publication

## Goal
Keep test launchers together under `ТЕСТЫ/`, provide technical and real-local-model runs via simple double clicks and publish only sanitized results to `test-reports`.

## Current state
The root contains two test BAT files. `scripts/verify_project.ps1` runs comprehensive offline technical tests by default and true local inference only if given `-RealSource`; it uploads an allowlisted report from an isolated temporary Git repository. The real-media validator requires an approximately 180-second source inside the project.

## Constraints
- Do not touch the `main` branch or user video originals.
- The full-model option must never pass if no real model was run.
- Normal technical testing must include Python, React, FFmpeg and the synthetic 180-second integration test.
- Use only project-local outputs; publish no videos, transcripts, prompts or secrets.
- Existing local test runs remain in `logs/tests` and `temp/verification-reports`.

## Implementation
1. Add an isolated 180-second extractor for a user-selected real video.
2. Extend verification to select video safely in interactive Windows mode and explicitly enforce real inference.
3. Move root testing BATs into a self-explanatory test folder; update docs and CI references.
4. Validate GitHub report sanitization, Python helper and actual Windows launchers.

## Validation
Python contract tests, helper tests, Windows PowerShell parsing and BAT smoke, standard backend/React and the dedicated 180-second technical E2E workflow.

## Risks and rollback
Model initialization and full local ASR/VLM are not available on GitHub runners and must run on the user's configured Windows PC. If the user cancels the file dialog, report a FAILED real-model step and still send a diagnostic. Revert the test-menu commits if a Windows launcher does not work.

## Progress
- [x] Inspect current verification and publication path.
- [ ] Add real-video selection/preparation.
- [ ] Create and connect two launchers in `ТЕСТЫ/`.
- [ ] Pass automated Linux and Windows verification.
- [ ] Have the user validate actual local models.
