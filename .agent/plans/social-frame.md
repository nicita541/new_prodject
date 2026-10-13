# Social publication frame

## Goal
Add a third composition option in the existing Studio: the complete video on a soft background inside a dark publication card, with user supplied channel and caption. Offer compact black and rounded post variants; post can show a supplied @handle. Content order is channel, caption, video. Save settings and render them in preview and MP4 export.

## Current state
Episode settings own cinema/portrait composition. FinishProfile.video owns rendering controls. app.media.render_part is shared by initial exports and app.studio_render finishing exports. Studio currently exposes two layout choices.

## Constraints
Preserve existing layouts and old profiles. No demo names, invented engagement counts, remote assets or branding. User text never enters FFmpeg syntax. No model or user montage runs during verification. All generated artifacts stay under the workspace.

## Implementation
1. Extend video finishing profile with plain/social frame style and bounded channel/caption text.
2. Draw a static transparent publication card using existing Pillow/fonts, feed it to shared FFmpeg renderer; retain whole source image.
3. Add the option and text fields to Studio episode settings and finishing controls, keep HTML text escaped, persist before launch.
4. Pass saved social appearance to initial rendering without changing analysis or plain-layout behavior.

## Validation
Focused Python API and render tests, existing Studio DOM smoke tests, syntax lint and build. Render a short synthetic local clip with hostile punctuation and Cyrillic; inspect image and MP4 dimensions/audio/duration.

## Risks and rollback
Pillow font support varies by platform; use the existing subtitle font resolver. Card text is rasterized, bounded and wrapped. Remove the new optional profile fields/UI and rendering branch to roll back; old profiles remain valid.

## Progress
- [x] Inspect current settings, preview and rendering owners.
- [x] Implement profile/card/renderer and initial render-only fingerprint.
- [x] Implement Studio controls and saving; frontend handed off for parallel product UI cleanup before final DOM checks.
- [x] Focused Python suite: 53 passed plus 10 subtests.
- [x] Real synthetic FFmpeg export 1.2 seconds and preview 0.6 seconds, both 1080×1920 with audio. Visually inspected rendered PNG; literal Cyrillic/punctuation preserved.
- [x] Final Studio DOM/lint/build after parallel UI cleanup, both selectable styles, literal text, source/output seek clocks, save and no duplicate overlays.
- [x] Removed synthetic parts/durations/waveform and empty-caption fallback; fixed latest montage navigation and active episode ownership guards.
- [x] Combined regression suite: 1434 passed, 636 subtests. Actual current compact/post export 1.2s and preview 0.6s, all 1080×1920 with audio; inspected PNGs under temp/social-frame-smoke/current.
