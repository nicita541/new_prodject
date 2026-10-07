# Semantic montage FIX STAGE 3

## Implemented data flow

Source optical-flow measurements from `media-evidence.json` now enter both the initial scene-setting profile and the finalized post-adjudication profile. Accepted cut density is `editing_score`; suppressed candidate counts stay diagnostic. Cut frequency and scene-change scores cannot assert physical movement. `motion_score` is nullable and its coverage is explicit. Semantic `action_score` requires accepted, selected, source-anchored unit evidence and actual ASR ownership.

`analysis_result()` persists one finalized profile, its initial measurements/settings and retention budget. The dramatic planner copies this exact profile and budget. Old saved analyses lacking a profile still derive a factual compatibility profile; they do not acquire motion evidence from shot scores.

`retention_allocation.py` reserves confirmed source state transitions and narrative action ranges before optional ranking. Each optional trial includes bounded continuity repair before cost comparison. Cost is the union of actual retained source ranges. The audit records mandatory proofs, bridge ranges, optional/mandatory durations, attempted candidate costs and specific overflow reasons. A required indivisible unit can exceed the soft maximum; this retains the unit and explains the excess.

Accepted bridge history remains mandatory after later optional additions, even when the resolver no longer needs to restore an already selected bridge. An oversized optional arc falls back to an individually costed candidate rather than forcing avoidable seed overflow. Measured motion, positive-evidence validation and allocator implementation hashes enter semantic cache identity.

## Calibration

Fresh offline evaluation uses the live profile implementation on **12 original source clips**: **8/8 training and 4/4 held-out** classifications match the coordinator's chronological source review. The 210-policy search uses training labels only. Held-out mutation cannot alter the fitted thresholds. Source hashes are checked against cached decoded optical flow and actual ASR. No semantic labels enter production profile inputs.

The selected training-only thresholds are speech .55, high motion .55 and low motion .20, with at least .35 trustworthy temporal measurement coverage. Four calibration regression methods cover live classification, training-only fit, held-out isolation and moving single-shot versus reverse-cut separation. The live report and rerunnable wrapper remain under `scratch/stage3-profile/calibration_live_stage3.json` and `calibrate_live_profile.py`.

This is short-clip pacing calibration from preserved source measurements, not a full semantic montage E2E. Optical flow includes camera movement and does not identify a physical action. Missing or sparse measurements remain explicit and choose balanced pacing.

## Files and regression protection

- `app/episode_profile.py`: version 2, continuous measured scores and stricter source evidence; 38 focused tests in `tests/test_episode_profile.py`.
- `app/analysis.py`: initial/final measured-profile handoff and persisted profile.
- `app/dramatic_planner.py`: exact finalized profile, allocation before optional budget and full audit.
- `app/retention_allocation.py`, `tests/test_retention_allocation.py`: 7 mandatory/optional/continuity/arc/overflow regressions.
- `app/semantic_identity.py`: actual motion and allocator cache dependencies.
- `tests/test_profile_planner_integration.py`: 5 real analysis/planner handoff and budget-pressure mechanisms.
- `tests/montage_fixtures.py`, `test_adaptive_montage.py`, `test_montage_regressions.py`: quota fixtures now supply the actual finalized profile budget. Existing output/duration/omission assertions remain. The old camera-candidate-as-action expectation now checks missing motion, then separately checks genuine optical-flow-shaped input.

No model calls or rendered videos are claimed for these mechanism tests. Stage 4 still owns automatic source-derived relations/arcs, verified omitted-unit continuity, final pre-render gates and actual raw-video A–J.

## Executed checks

Full Python suite: **799 passed in 93.460 seconds**. Focused profile: 38 passed, including all 4 optional cached real-source calibration checks in this workspace; no calibration skips. Allocator and integration: 7 and 5 passed. Related adaptive/long montage checks retain their original duration and omission assertions. Legacy UI: 24 passed. `git diff --check` passed. Read-only review reproduced both allocator regressions before their fixes and verified them afterward.
