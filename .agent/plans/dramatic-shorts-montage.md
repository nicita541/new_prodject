# ExecPlan: Dramatic Shorts Montage & Narrative Condensation

## Goal
Replace the sequential arithmetic slicing (which kept 34 of 36 scenes across 15 long slices of ~90s) with genuine **Dramatic Shorts Montage**:
1. **Narrative Condensation**: Distinguish core plot arcs from incidental exposition/filler, condensing a 23-minute episode into 5–8 high-impact, standalone-watchable Shorts.
2. **Three-Beat Dramatic Structure**: Each Short follows Hook (0–3s) → Story Core (40–80s) → Cliffhanger/Punchline (ending beat).
3. **Snappy Pacing**: Trim dead conversational air between dialogue turns down to 0.4–0.8s while preserving full speech handles and Narrative Bridges.

---

## Current state
- `global_story_review` in `app/story_review.py` currently explicitly instructs the model: `"Preserve nearly all short reactions, jokes, banter and atmospheric exchanges even without plot progress. No target duration, clip count or removal percentage."`
- Consequently, DeepSeek keeps 34 of 36 scenes (`story.json`: 34 keep, 2 omit credits).
- `app/planner.py` takes the ~1350 seconds of retained footage and sequentially packs it into 15 parts targeting 90 seconds. Inside each part, almost nothing is cut (1–2 cuts per part).
- The user observed that the timeline shows 15 solid blocks of 1.5 minutes covering the entire episode without actual condensation.

---

## Constraints
1. **Zero hardcoding**: No series names, timestamps, or fixed thresholds tied to specific anime.
2. **Workspace containment**: All changes remain inside `F:\new_prodject`.
3. **Safety of causality**: Never drop a Narrative Bridge ($A \to Action \to B$) or an unresolved prerequisite needed to understand future events.
4. **Speech preservation**: Spoken words and consonants must never be clipped (`_speech_lead` / `_speech_tail`).
5. **Deterministic fallback**: If model review fails or is offline, the system safely falls back without crashing.
6. **100% Green test suite**: All 446 existing unit tests must continue to pass.

---

## Implementation

### Milestone 1: Editorial Policy & Dramatic Story Review (`app/story_review.py`, `app/editorial.py`)
- In `app/editorial.py`, define dramatic condensation mode: prioritize main narrative conflict and high-emotion/high-stakes turns over casual background banter and walking.
- Update `global_story_review()` prompt and schema to support `dramatic_shorts` mode:
  - Identify core narrative arcs (Main Story vs Fluff/Secondary Exposition).
  - Explicitly select events that form 5–8 high-interest Shorts.
  - Require omissions to drop low-stakes filler scenes while strictly safeguarding Narrative Bridges and state transitions.
- Update `apply_global_selection()` to respect the dramatic selection policy while enforcing causality safety.

### Milestone 2: Snappy Conversational Pacing (`app/pacing.py`)
- In dialogue exchanges, trim dead silence (>1.2s) between consecutive speaker turns down to 0.4–0.8s.
- Preserve full speech buffers (`SPEECH_LEAD`, `SPEECH_TAIL`).
- Keep micro-action beat condensation for long transition units ($>3.0$s).

### Milestone 3: Dramatic Part Planning (`app/dramatic_planner.py` / `app/planner.py`)
- Implement `build_dramatic_plan()`:
  - Group condensed events by narrative beats rather than arithmetic 90-second grids.
  - Structure each part:
    - **Hook (0–3s)**: Start immediately on the initial spoken line or visual beat, eliminating dead pre-speech lead-in.
    - **Story Core (40–80s)**: High-density narrative progression.
    - **Ending**: Snap to verified `cliffhanger`, `punchline`, or `closure` beats from `app/endings.py`.
  - Target part count: 5–8 compact Shorts (instead of 15).

### Milestone 4: Unit Testing & Verification
- Add `tests/test_dramatic_planner.py` covering:
  - Core arc condensation vs filler elimination.
  - Hook lead-in trimming.
  - Cliffhanger boundary alignment.
  - Preservation of speech handles and Narrative Bridges.
- Ensure all 446+ tests pass.

### Milestone 5: End-to-End Pipeline Execution
- Run updated dramatic pipeline on Episode 1 («Забота об одарённой девушке»).
- Verify output parts in Web Studio at `http://127.0.0.1:8765`.

---

## Validation
- `tools/python/python.exe -m unittest discover -s tests -q` passes 100%.
- Plan produces 5–8 concentrated Shorts with varied, dramatic lengths (45–85s).
- Web Studio renders preview with crisp, dynamic pacing.

---

## Risks and Rollback
- Tag `checkpoint-baseline-start` and branch `checkpoint-baseline-start` were established before these changes.
- Rollback command if needed: `git checkout checkpoint-baseline-start`.

---

## Progress
- [x] Checkpoint baseline commit `3c65d16` tagged as `checkpoint-baseline-start`.
- [x] Created working branch `codex/dramatic-montage`.
- [x] Drafted ExecPlan for dramatic shorts montage.
- [x] Milestone 1: Editorial policy & dramatic story review (`app/editorial.py`, `app/story_review.py`, `app/analysis.py`).
- [x] Milestone 2: Snappy conversational pacing (`app/pacing.py`, `_compress_dialogue_turns`).
- [x] Milestone 3: Dramatic part planning (`app/dramatic_planner.py`, `app/planner.py`, `app/pipeline.py`).
- [x] Milestone 4: Unit tests suite (`tests/test_dramatic_planner.py`, 450/450 tests green).
- [ ] Milestone 5: Pipeline execution & Web Studio verification (running on Episode 1).

