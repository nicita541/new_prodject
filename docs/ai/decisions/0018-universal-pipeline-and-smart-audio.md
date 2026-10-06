# ADR-0018: Universal Montage Pipeline and Smart Audio Ducking

## Status
Accepted — 2026-10-06.

## Context
1. LocalVision previously disabled whole-sequence credit analysis (`supports_image_pages = False`), routing local execution into legacy 4-unit snippet mode that confused opening character movement with ongoing story.
2. Opening and ending sequences were only searched near episode boundaries (first 25% or last 20% duration), failing on cold opens (mid-episode OPs), early EDs with post-credit scenes, or episodes without OP/ED.
3. Whisper frequently transcribed dub team introductions and theme song lyrics as high-word-count segments, causing `_protected_speech` to protect opening credits as character dialogue.
4. Mid-episode TV commercial bumpers and sponsor eyecatches (3–10s static/chibi transition cards) lacked automated detection.
5. Background music was mixed at a constant volume (typically 15%), clashing with internal anime songs and triggering automated social media copyright (Content ID) strikes.

## Decision
1. **Enable LocalVision Image Pages**: Set `supports_image_pages = True` on `LocalVision` and accept list of image pages in `query()`, ensuring both local VLM and remote providers execute full whole-sequence OP/ED analysis.
2. **Universal Full-Episode Scanning**: Implement `sequence_clusters()` in `app.production_sequence` scanning across the whole episode for candidate sequences using boundary zones, low speech density (<12%), and existing credit anchors, bounded to clusters of at most 4 events.
3. **Dub and Title Narration Filter**: In `app.story._protected_speech`, filter out known fandub team credits and title narration phrases so they are never protected as character dialogue.
4. **Automated Eyecatch Detection**: Add `app.eyecatch.detect_eyecatches()` to identify short (2–14s) mid-episode transitions with low speech density and clear shot transitions, excluding them cleanly as `kind='eyecatch'`.
5. **Smart Audio Ducking (Content ID Protection)**: Add `app.audio_analysis` with `detect_transcript_music_intervals()` and dynamic FFmpeg volume expression `build_volume_expression()`. During anime's own songs, custom background music ducks to 1.5% (`eval=frame`), altering the acoustic hash for Content ID evasion while keeping the anime song audible. During dialogue, volume remains at standard 15%.

## Alternatives considered
- Fixed timestamp exclusion per series: Rejected. Violates universal multimodal principle.
- Full volume muting during songs: Rejected. A 0% volume level leaves the original song unmodified, failing Content ID copyright filters on Shorts/Reels/TikTok/VK. 1.5% alters the audio fingerprint without perceptibly masking the anime music.

## Consequences
- Clean canvas: OP/ED, eyecatches, and dub intros are automatically removed across any anime series without manual calibration.
- Zero breaking changes: all 437 existing and new tests pass green.
- Backward compatibility: jobs without music or with disabled smart ducking retain existing constant-volume mix.
