# ExecPlan: Universal 3-Stage Montage Pipeline

## Goal

Make the montage pipeline truly universal and multimodal: any anime series loads, OP/ED/eyecatches are detected automatically without per-series calibration, background music ducks intelligently when the anime has its own songs, and shorts are cut at dramatic beats rather than arithmetic time slices.

The pipeline runs in three sequential stages:
1. **Clean Canvas** — detect and remove OP, ED, TV bumpers/eyecatches.
2. **Smart Audio & Copyright** — duck user's background music during anime's own music; keep it at comfortable levels during dialogue.
3. **Dramatic Shorts** — build Hook→Story→Cliffhanger parts instead of equal-time chunks.

## Current state

### What works
- `production_sequence.py` (`clean_whole_sequences`) classifies whole OP/ED via VLM when `supports_image_pages=True`. Verified on «Перекур»: OP 88.17–182.32s, ED 1332.86–1433.28s.
- `story.py` (`refine_story`) condenses events with dialogue protection and editorial profiles.
- `music.py` picks background tracks with a single flat `volume` (default 0.15) for the entire part.
- `media.py` (`render_part`) mixes background music at a constant volume via FFmpeg `amix`.
- `planner.py` builds plans with soft 90s/hard 120s targets and scene-ending proposals.
- `pipeline.py` orchestrates analysis→plan→render with 2-worker parallel export.

### What fails
1. **LocalVision bypass** (`production.py:114`): `clean_sequences` checks `supports_image_pages` — `LocalVision` returns `False`, so the whole-sequence detector never runs for local VLM. Falls through to the obsolete 4-unit snippet mode that mistakes OP character movement for story.
2. **ED cluster anchor blindness**: `original_clusters` only groups events where coarse 40s scanning set `contains_credits: True`. Credits rolling over city/night art without giant titles get missed at coarse scanning.
3. **ASR/dub lyrics interference**: Whisper transcribes Russian dub intros, episode title recitation, and song lyrics. `_protected_speech` treats these as character dialogue, preventing OP/ED unit removal.
4. **No eyecatch/bumper detection**: TV bumpers ("Мы вернёмся после рекламы" / sponsor cards between A-part and B-part) are never identified.
5. **Flat music volume**: Background music plays at constant 15% regardless of whether the anime has its own insert songs, concerts, or musical scenes.
6. **Arithmetic part lengths**: Parts target 90s ± 30s via nearest-boundary packing. No Hook/Cliffhanger/dramatic beat structure.

## Constraints

1. **ZERO hardcoding**: No series names, fixed timestamps, or episode-specific rules in production code.
2. **Workspace only**: All files, caches, dependencies stay in `F:\new_prodject`.
3. **Backward compatibility**: Existing jobs, caches, editorial profiles, saved plans remain readable. New pipeline stages have version bumps in cache signatures.
4. **Audio protection**: During anime's own music → user background at 1–2% (Content ID bypass). During dialogue → 12–15%. During quiet/whisper → 5–7%.
5. **Preserve tested behavior**: 428 existing tests must continue passing. New stages get new tests.
6. **No global installs**: Use only tools and models already in the workspace.

## Implementation

### Milestone 1: Enable whole-sequence detection for LocalVision

**Problem**: `clean_sequences` in `production.py:113-116` gates on `supports_image_pages`. LocalVision doesn't set this.

**Fix**:
1. Add `supports_image_pages = True` property to `LocalVision` class in `vision.py`. The llama.cpp server already supports multiple image inputs; the flag was simply never set.
2. Remove the `supports_image_pages` gate in `clean_sequences` — always route to `clean_whole_sequences`. The obsolete 4-unit snippet path becomes dead code; keep it behind a flag for rollback.
3. Bump `VERSION` in `production_sequence.py` to 11 to invalidate old caches.
4. Add focused tests verifying LocalVision routes to whole-sequence detection.

### Milestone 2: Full-episode OP/ED/insert scanning

**Problem**: Coarse 40s visual scanning misses credits over subtle backgrounds. Additionally, OP/ED are **not** always at episode boundaries — cold opens can push OP to the middle; ED can play early with a post-credits scene after; some episodes have no OP/ED at all; final episodes sometimes embed OP/ED into the narrative.

**Fix**:
1. Add `ensure_sequence_candidates(events, transcript, shots)` in `production_sequence.py` that scans **every event across the entire episode**, not just boundary zones. Candidate detection uses multi-signal scoring:
   - **Audio energy**: sustained musical segment (high RMS, low speech density) anywhere in the timeline.
   - **Visual repetition**: frame similarity to known OP/ED frames from other episodes of the same series (if available from prior jobs).
   - **Duration heuristic**: OP is typically 60–100s, ED 60–120s — but these are soft hints, never hard filters.
   - **Speech density**: events with < 10% speech density and high audio energy are strong candidates.
   - Events scoring above threshold get `candidate_sequence: True` regardless of position.
2. Modify `clean_whole_sequences` to use `ensure_sequence_candidates` instead of relying solely on coarse `contains_credits` flags from the initial analysis pass. Fall back to `original_clusters` for events already flagged.
3. Handle edge cases explicitly:
   - **No OP/ED found**: pipeline proceeds normally — zero removal is a valid outcome.
   - **OP mid-episode** (cold open): OP detected at any position is valid; pre-OP and post-OP content both kept as story.
   - **ED followed by post-credits scene**: ED boundaries are precise — content after ED's `last_unit` is kept as story if it has dialogue/action.
   - **Multiple OP/ED** (rare recap episodes): each is detected independently.
4. Ensure `_protected_speech` in `story.py` filters out segments where word probability is consistently low (< 0.4) — these are likely ASR artifacts over music, not real dialogue.
5. Add a `speech_role` check: if a segment's text matches known dub intro patterns (e.g., "В ролях:", "Режиссёр:", episode title recitation), mark it as `title_narration` rather than protected speech.
6. Tests: OP detection for «Перекур» Episode 1 (88s–182s), ED (1332s–1433s). Include negative test: episode with no OP/ED → zero removal. Include mid-episode OP test with synthetic cold-open fixture.

### Milestone 3: Eyecatch/TV bumper detection

**Problem**: Mid-episode sponsor cards and "after the break" bumpers are never identified.

**Fix**:
1. Add `detect_eyecatches(events, transcript, shots, vision)` in a new module `app/eyecatch.py`.
2. Eyecatches are typically 3–10 second static/animated cards with sponsor text or "つづく" / transition graphics, occurring near the episode midpoint.
3. Detection strategy:
   - Scan events near 40–60% of episode duration.
   - Look for events with: very short duration (< 15s), no dialogue, high visual contrast change (shot boundaries on both sides), and visible text overlay.
   - If VLM is available, submit candidate frames for classification: "Is this a TV commercial bumper / eyecatch / sponsor card?"
4. Detected eyecatches are excluded from story condensation, same as OP/ED.
5. Mark in events as `kind: 'eyecatch'` with `eyecatch_confidence`.
6. Tests with synthetic fixtures mimicking eyecatch patterns.

### Milestone 4: Smart audio ducking (Content ID protection)

**Problem**: Background music plays at flat 15% volume, doesn't react to anime's own music.

**Fix**:
1. Add `app/audio_analysis.py` module:
   - `detect_music_segments(source: Path, workdir: Path) -> list[dict]` — Uses FFmpeg's `silencedetect` + `astats` to identify high-energy non-speech segments.
   - `classify_audio_segments(segments, transcript) -> list[AudioSegment]` — Cross-references with ASR transcript: segments with music energy but no recognized speech → "anime_music". Segments with speech → "dialogue". Segments with low energy → "quiet".
   - Cache results keyed by source identity.

2. Extend `music.py` config with new ducking modes:
   ```python
   DEFAULT_CONFIG = {
       "enabled": True,
       "volume": 0.15,           # base dialogue volume
       "volume_during_music": 0.015,  # 1.5% during anime's own music
       "volume_quiet": 0.07,     # 7% during whispers
       "smart_ducking": True,    # enable/disable adaptive volume
       "fade_in": True,
       "fade_out": True,
       ...
   }
   ```

3. Modify `render_part` in `media.py`:
   - Accept `audio_segments: list[dict] | None` parameter.
   - When `smart_ducking` is enabled and segments are provided, generate a time-varying volume expression in FFmpeg instead of a flat `volume=0.15`:
     ```
     volume='if(between(t,T1,T2),0.015,if(between(t,T3,T4),0.07,0.15))'
     ```
   - The expression maps each cut's time range to the appropriate volume level based on the audio classification of that source segment.

4. Update `pipeline.py` to:
   - Run audio analysis after `analyze()` but before `build_plan()`.
   - Pass `audio_segments` through to `render_part` via `background_music` dict.

5. Tests:
   - Unit test volume expression generation for known segment layouts.
   - Integration test that a rendered part with anime music segments uses the duck volume.
   - Verify limiter prevents clipping.

### Milestone 5: Dramatic part structure (Hook → Story → Cliffhanger)

**Problem**: Parts are cut at arithmetic 90s targets, not at dramatically meaningful boundaries.

**Fix**:
1. Extend `app/endings.py` (already exists for scene-ending proposals) with:
   - `classify_dramatic_moment(event, position_in_episode) -> str` — Returns one of: 'hook_potential', 'tension_peak', 'emotional_beat', 'cliffhanger', 'resolution', 'neutral'.
   - Uses retained dialogue summaries and VLM scene classifications.

2. Add `app/dramatic_planner.py`:
   - `build_dramatic_plan(analysis, audio_segments) -> Plan` replaces `build_plan` when dramatic mode is enabled.
   - Strategy:
     - **First 3 seconds of each part** = Hook: start with a visually striking or emotionally loaded moment. If the part begins mid-scene, use the most dramatic frame as a flash-forward tease.
     - **Core 60–110 seconds** = Story: the actual narrative progression.
     - **Last 5–10 seconds** = Cliffhanger/Punchline: end on an unresolved question, a reaction shot, or a comedic beat. Never cut mid-sentence.
   - Part boundaries prefer: unanswered questions, reveal moments, character decisions, comedic punchlines.
   - Avoid ending on: exposition, travel shots, establishing shots, mid-dialogue.

3. Integrate into `pipeline.py` as an alternative planner mode, controlled by editing options:
   ```python
   options = {"dramatic_parts": True}  # default True for new jobs
   ```

4. Tests:
   - Verify hook/cliffhanger boundary selection on known event sequences.
   - Regression: existing plan tests still pass when dramatic mode is off.
   - End-to-end: dramatic plan produces valid parts within 70–120s range.

### Milestone 6: Integration, cross-validation, and documentation

1. Run the full pipeline on «Перекур» Episode 1:
   - Verify OP 88–182s is 100% removed.
   - Verify ED 1332–1433s is 100% removed.
   - Verify background music ducks during any anime insert songs.
   - Verify parts start with hooks and end at dramatic beats.

2. Cross-validate on other available series in the repo.

3. Run complete test suite: all 428+ tests must pass.

4. Update:
   - `docs/ai/architecture.md` — new pipeline stages.
   - `docs/ai/decisions/` — ADR for universal detection and smart ducking.
   - `docs/ai/known-issues.md` — remove resolved issues, add new limitations.

## Validation

- All existing 428 tests pass without modification.
- New focused tests for each milestone (target: 30+ new tests).
- OP/ED detection accuracy on «Перекур» Episode 1: OP within ±5s of ground truth (88–182s), ED within ±5s of ground truth (1332–1433s).
- Smart ducking: rendered audio has measurably lower background music level during anime music segments vs. dialogue segments.
- Dramatic parts: no part ends mid-sentence; each part's last 5s contains a tension peak, question, or punchline (verified by inspection).
- Full pipeline run completes without errors on at least 2 different anime series.

## Risks and rollback

| Risk | Mitigation |
|------|-----------|
| LocalVision image-page support breaks llama.cpp queries | Gate behind a runtime capability check; fall back to single-image mode |
| Aggressive OP/ED zone scanning removes story near episode boundaries | Require strong visual anchors (staff credits) before removing; uncertain → preserve |
| Audio analysis misclassifies dialogue as music | Cross-reference with ASR transcript; only duck when speech density is < 5% in segment |
| Smart ducking FFmpeg expression errors | Validate expression syntax in tests; fall back to flat volume on error |
| Dramatic planner produces very short (<60s) or very long (>120s) parts | Enforce hard bounds; fall back to current planner if dramatic boundaries are too sparse |
| Cache invalidation from version bumps causes full reanalysis | Only bump versions for changed stages; reuse valid upstream caches |

**Rollback**: Each milestone is a separate commit. Revert to prior commit and rerun from preserved inputs. No data migration needed — old caches are simply ignored when versions don't match.

## Progress

- [x] Milestone 1: Enable whole-sequence detection for LocalVision
- [x] Milestone 2: Full-episode OP/ED/insert scanning
- [x] Milestone 3: Eyecatch/TV bumper detection
- [x] Milestone 4: Smart audio ducking (Content ID protection)
- [x] Milestone 5: Dramatic part structure (Hook → Story → Cliffhanger)
- [x] Milestone 6: Integration, cross-validation, and documentation
