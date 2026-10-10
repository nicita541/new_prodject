# KADR — complete verification timing

**Elapsed until reporting:** 1811.1 s (30m 11.1s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.4 s (0m 0.4s) | 0.02% |
| python_dependencies | PASS | 0.7 s (0m 0.7s) | 0.04% |
| python_tests | PASS | 137.8 s (2m 17.8s) | 7.61% |
| react_tests | PASS | 17.5 s (0m 17.5s) | 0.96% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.5 s (0m 2.5s) | 0.14% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 83.8 s (1m 23.8s) | 4.63% |
| prepare_real_source | PASS | 10.7 s (0m 10.7s) | 0.59% |
| real_model_3min | TIMEOUT | 1548.6 s (25m 48.6s) | 85.51% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.7 s (0m 0.7s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 70.7 s (1m 10.7s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.2 s (0m 1.2s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.6 s (0m 8.6s) |
| ffmpeg_finishing_zoom_music_and_edited_captions | passed | 1.5 s (0m 1.5s) |
| real_studio_http_source_plan_mp4_srt_and_range | passed | 0.2 s (0m 0.2s) |

## 3. Real ASR/VLM + render acceptance substeps (inside real_model_3min)

| Step | Status | Duration |
| --- | --- | ---: |

## 4. Real production stages in first-seen order

| Stage | Completed calls | Unfinished | Inclusive time | % of production |
| --- | ---: | ---: | ---: | ---: |
| pipeline | 0 | 1 | not measured | — |
| prepare | 1 | 0 | 0.2 s (0m 0.2s) | — |
| transcribe | 1 | 0 | 29.5 s (0m 29.5s) | — |
| scenes | 1 | 0 | 371.3 s (6m 11.3s) | — |
| shot_detection | 1 | 0 | 2.5 s (0m 2.5s) | — |
| media_perception | 1 | 0 | 6.9 s (0m 6.9s) | — |
| scene_detection | 1 | 0 | 360.3 s (6m 0.3s) | — |
| semantic_boundary | 74 | 0 | 303.7 s (5m 3.7s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 1 | 0 | 817.3 s (13m 37.3s) | — |
| scene_analysis | 20 | 0 | 595.1 s (9m 55.1s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 0 | 1 | not measured | — |
| condense | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **154**, responses: **153**, errors: **0**.
Sum of response durations: **943.7 s (15m 43.7s)**; median: 4.2 s (0m 4.2s).

## 7. Bottleneck candidates

Slowest verification step: **real_model_3min — 1548.6 s (25m 48.6s)**.
Slowest detailed production stage: **scene_analysis — 595.1 s (9m 55.1s)**.

Only fixed internal check/stage names and numeric measurements are published.
