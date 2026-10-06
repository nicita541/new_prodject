# ExecPlan: Adaptive Scene Thresholds and Narrative Bridge Continuity

This ExecPlan details the implementation of two foundational editing improvements:
1. **Adaptive Motion-Aware Cut Detection** in `app/media_probe.py`: dynamically adjusting scene cut detection thresholds based on local motion/cut density (calm dialogue ~0.20, dynamic action/sakuga up to 0.45–0.55), preventing authorial action shots from being shredded into micro-fragments.
2. **Narrative Bridge & State-Change Continuity** in `app/story_review.py`, `app/pacing.py`, and `app/planner.py`: identifying non-verbal state-changing transitions ($A \to \text{Action} \to B$, e.g., capture, door entry, injury) so they are preserved rather than pruned as "empty silence", combined with **Micro-Action Beat Condensation** to keep shorts fast-paced.

---

## Goal
- Eliminate false shot cuts during high-motion anime action (sakuga, camera pans) while retaining fine-grained precision during calm dialogue.
- Prevent narrative breakages ("teleportation" jump cuts) caused by deleting essential non-verbal transitions, while keeping shorts concise by condensing long non-verbal transitions to key action beats.
- Verify on the full unit test suite (100% green) and run on a complete real anime episode.
- Deliver results accessible via the local web app (`http://127.0.0.1:8765`).

---

## Current State
- `app/media_probe.py`: uses static `SCENE_THRESHOLD = 0.20` in `detect_shots()`.
- `app/story_review.py`: checks global story continuity with `keep` / `omit`, but does not explicitly score causality triplets `[before, current, after]` or label `narrative_bridge`.
- `app/pacing.py`: removes speech-free pauses categorized as `waiting`, `repeat`, `scenery`, but sometimes over-retains neutral scenery or risks cutting crucial non-verbal action if not marked with high importance.
- `tests/`: 437 passing unit tests.

---

## Implementation Milestones

### Milestone 1: Adaptive Motion-Aware Cut Detection (`app/media_probe.py`)
- Implement `adaptive_scene_threshold(scene_events, duration)` algorithm:
  - Analyze candidate scene transitions using a multi-resolution or density-aware filter.
  - Calculate local motion/cut activity over a sliding temporal window (10–20s).
  - Elevate the effective scene threshold during continuous high visual flux (action/sakuga) to 0.35–0.50.
  - Maintain fine threshold (0.18–0.22) during calm, low-motion dialogue.
  - Enforce minimum shot duration pacing to eliminate sub-second jitter during rapid camera pans.
- Add unit tests verifying adaptive threshold behavior on calm vs. rapid motion profiles.

### Milestone 2: Narrative Bridge & State-Change Model (`app/story_review.py`)
- Formalize `Narrative Bridge` concept in VLM schemas and prompt instructions:
  - Identify causal state transitions ($A \xrightarrow{\text{Action}} B$) where omitting current causes narrative incoherence in $B$.
  - Add `narrative_bridge`, `state_change`, and `causal_continuity` evaluation to VLM analysis and story review.
  - Protect narrative bridge units from whole-event pruning, even with `speech = 0.0`.
- Add unit tests validating narrative bridge retention against empty scenery pruning.

### Milestone 3: Micro-Action Beat Condensation (`app/pacing.py` & `app/planner.py`)
- Implement action beat condensation for narrative bridges:
  - If a non-verbal narrative bridge exceeds 3.0s, condense it to key action phases (onset of action, climax/transition beat, resolution) rather than either keeping 5+ seconds of silence or dropping it entirely.
  - Ensure boundaries align with clean shot boundaries and speech handles.
- Add unit tests verifying micro-action condensation.

### Milestone 4: Regression Protection & Full Unit Test Suite
- Run the full test suite (`python -m unittest discover -s tests -q`).
- Ensure all 437+ tests pass with zero regressions.

### Milestone 5: Full Anime Episode Run & Web Studio Validation
- Run the enhanced pipeline on a complete anime episode.
- Ensure the FastAPI server is running as a daemon on `127.0.0.1:8765`.
- Verify the generated parts appear in the web player and review timeline.

---

## Validation
- `tools\python\python.exe -m unittest discover -s tests -q` -> 100% pass.
- Verification of adaptive shot boundaries in generated `shots.json`.
- Visual and playback verification at `http://127.0.0.1:8765`.

---

## Progress
- [ ] Milestone 1: Adaptive Motion-Aware Cut Detection
- [ ] Milestone 2: Narrative Bridge & State-Change Model
- [ ] Milestone 3: Micro-Action Beat Condensation
- [ ] Milestone 4: Regression Protection & Unit Tests
- [ ] Milestone 5: Full Anime Episode Run & Web Studio Verification
