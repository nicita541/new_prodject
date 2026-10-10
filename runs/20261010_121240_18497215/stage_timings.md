# KADR — complete verification timing

**Elapsed until reporting:** 1808.3 s (30m 8.3s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.3 s (0m 0.3s) | 0.02% |
| python_dependencies | PASS | 0.7 s (0m 0.7s) | 0.04% |
| python_tests | PASS | 137.9 s (2m 17.9s) | 7.63% |
| react_tests | PASS | 7.0 s (0m 7.0s) | 0.38% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.5 s (0m 2.5s) | 0.14% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 90.7 s (1m 30.7s) | 5.02% |
| prepare_real_source | PASS | 11.2 s (0m 11.2s) | 0.62% |
| real_model_3min | TIMEOUT | 1551.5 s (25m 51.5s) | 85.8% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.6 s (0m 0.6s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 77.5 s (1m 17.5s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.2 s (0m 1.2s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.7 s (0m 8.7s) |
| ffmpeg_finishing_zoom_music_and_edited_captions | passed | 1.4 s (0m 1.4s) |
| real_studio_http_source_plan_mp4_srt_and_range | passed | 0.2 s (0m 0.2s) |

## 3. Real ASR/VLM + render acceptance substeps (inside real_model_3min)

| Step | Status | Duration |
| --- | --- | ---: |

## 4. Real production stages in first-seen order

| Stage | Completed calls | Unfinished | Inclusive time | % of production |
| --- | ---: | ---: | ---: | ---: |
| pipeline | 0 | 1 | not measured | — |
| prepare | 1 | 0 | 0.2 s (0m 0.2s) | — |
| transcribe | 1 | 0 | 28.9 s (0m 28.9s) | — |
| scenes | 1 | 0 | 368.7 s (6m 8.7s) | — |
| shot_detection | 1 | 0 | 2.5 s (0m 2.5s) | — |
| media_perception | 1 | 0 | 6.8 s (0m 6.8s) | — |
| scene_detection | 1 | 0 | 357.9 s (5m 57.9s) | — |
| semantic_boundary | 74 | 0 | 301.6 s (5m 1.6s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 1 | 0 | 800.0 s (13m 20.0s) | — |
| scene_analysis | 20 | 0 | 577.1 s (9m 37.1s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 0 | 1 | not measured | — |
| condense | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **151**, responses: **150**, errors: **0**.
Sum of response durations: **962.6 s (16m 2.6s)**; median: 4.2 s (0m 4.2s).

## 7. Local llama.cpp per-model and per-task profile

| Model | Task | Requests | Pending | p50 HTTP | p95 HTTP | Prompt tokens | Completion tokens | Reasoning tokens | Length stops | Prefill p50 | Decode p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| story9b | choose_units | 3 | 1 | 163.4 s (2m 43.4s) | 170.1 s (2m 50.1s) | 4182.0 | 1216.0 | 0 | 0 | 17568.861 ms | 143689.007 ms |
| visual4b | scene_analysis | 72 | 0 | 4.6 s (0m 4.6s) | 5.4 s (0m 5.4s) | 148245.0 | 19933.0 | 0 | 0 | 1146.918 ms | 3170.588 ms |
| visual4b | semantic_boundary | 76 | 0 | 3.8 s (0m 3.8s) | 4.8 s (0m 4.8s) | 112644.0 | 17837.0 | 0 | 0 | 810.89 ms | 2925.514 ms |

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 6.1 s (0m 6.1s)
- visual4b / ok / GPU: 3.5 s (0m 3.5s)
- story9b / ok / GPU: 12.6 s (0m 12.6s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1551.5 s (25m 51.5s)**.
Slowest detailed production stage: **scene_analysis — 577.1 s (9m 37.1s)**.

Only fixed internal check/stage names and numeric measurements are published.
