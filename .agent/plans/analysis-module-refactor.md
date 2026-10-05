# ExecPlan: Modular Refactor of `app/analysis.py`

## Goal
Decompose the 822-line monolithic `app/analysis.py` into focused, cohesive modules with single responsibilities (media probing & shot detection, local vision & storyboarding, story structuring & LLM review, and pipeline orchestration) while maintaining 100% backward compatibility for all existing imports and tests.

## Current state
`app/analysis.py` mixes multiple unrelated concerns:
1. Low-level subprocess execution, media probing via `ffprobe`, PySceneDetect shot detection, and transcript normalization (~130 lines).
2. Local vision (VLM) model session management and storyboard frame extraction (~180 lines).
3. Candidate story units generation, event validation, omission checks, and global LLM review routing (~200 lines).
4. Pipeline coordination, provider dispatch, atomic JSON persistence, and main `analyze()` pipeline (~310 lines).

This violates single responsibility, makes targeted unit testing slower, and increases cognitive overhead.

## Constraints
1. **Zero breaking changes:** Every public function and class currently in `app/analysis.py` must remain importable from `app.analysis` with identical signatures and return values.
2. **Clean imports:** Avoid circular dependencies between submodules.
3. **Execution rules:** All code changes must be validated by running the existing pytest suite.

## Implementation Milestones

### Milestone 1: Extract Media & ASR Preprocessing (`app/media_probe.py`)
- Extract `run_process`, `probe_media`, `detect_shots`, `shot_checkpoint`, `analysis_windows`, and `normalize_transcript`.
- Re-export them from `app/analysis.py`.
- Run validation tests.

### Milestone 2: Extract Vision & Storyboard Processing (`app/vision.py`)
- Extract `LocalVision`, `vision_session`, `storyboard_times`, and `storyboard`.
- Re-export them from `app/analysis.py`.
- Run validation tests.

### Milestone 3: Extract Story Review & Selection (`app/story_review.py`)
- Extract `validated_event`, `candidate_units`, `apply_unit_selection`, `validate_global_omissions`, `apply_global_selection`, and `global_story_review`.
- Re-export them from `app/analysis.py`.
- Run validation tests.

### Milestone 4: Streamline `app/analysis.py` & Final Verification
- Keep pipeline orchestration (`analyze`), cache utilities (`atomic_json`, `load_json`), provider routing, and facade exports.
- Run complete test suite across all related modules (`test_analysis.py`, `test_analysis_provider.py`, `test_deepseek.py`, `test_story.py`, `test_media.py`, etc.).
- Update documentation in project-map / project notes if appropriate.

## Validation
- `tests/test_analysis.py` passes all 19 tests.
- `tests/test_analysis_provider.py`, `tests/test_deepseek.py`, `tests/test_story.py`, `tests/test_titles.py`, `tests/test_part_context.py` pass all 64 tests.
- `tests/test_closing.py`, `tests/test_pacing.py`, `tests/test_quality.py`, `tests/test_source_roles.py`, `tests/test_storyboard.py` pass all 75 tests.

## Risks and rollback
- **Risk:** Circular imports between `analysis.py` and extracted modules.
  - *Mitigation:* Extracted modules only import low-level helpers or standard libraries, never importing `analysis.py`.
- **Rollback:** `git checkout app/analysis.py` and delete new files.

## Progress
- [x] Baseline test verification (158 passing tests)
- [x] Milestone 1: `app/media_probe.py` (Subprocess execution, ffprobe probing, shot detection, windows, transcript normalization)
- [x] Milestone 2: `app/vision.py` (LocalVision VLM server management, session routing, and storyboard generation)
- [x] Milestone 3: `app/story_review.py` (Candidate story units, event validation, global omission validation, and LLM review)
- [x] Milestone 4: Streamlined `app/analysis.py` & validation (100% backward compatibility, all 417 repository tests passing)
