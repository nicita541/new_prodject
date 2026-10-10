# KADR — complete verification timing

**Elapsed until reporting:** 1808.7 s (30m 8.7s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.4 s (0m 0.4s) | 0.02% |
| python_dependencies | PASS | 0.7 s (0m 0.7s) | 0.04% |
| python_tests | PASS | 139.1 s (2m 19.1s) | 7.69% |
| react_tests | PASS | 10.5 s (0m 10.5s) | 0.58% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.6 s (0m 2.6s) | 0.14% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 97.7 s (1m 37.7s) | 5.4% |
| prepare_real_source | PASS | 10.7 s (0m 10.7s) | 0.59% |
| real_model_3min | TIMEOUT | 1539.5 s (25m 39.5s) | 85.12% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.7 s (0m 0.7s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 84.4 s (1m 24.4s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.3 s (0m 1.3s) |
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
| prepare | 1 | 0 | 0.3 s (0m 0.3s) | — |
| transcribe | 1 | 0 | 29.1 s (0m 29.1s) | — |
| scenes | 1 | 0 | 367.3 s (6m 7.3s) | — |
| shot_detection | 1 | 0 | 2.5 s (0m 2.5s) | — |
| media_perception | 1 | 0 | 6.7 s (0m 6.7s) | — |
| scene_detection | 1 | 0 | 356.5 s (5m 56.5s) | — |
| semantic_boundary | 74 | 0 | 299.8 s (4m 59.8s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 1 | 0 | 766.9 s (12m 46.9s) | — |
| scene_analysis | 18 | 0 | 555.2 s (9m 15.2s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 0 | 1 | not measured | — |
| condense | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **149**, responses: **148**, errors: **0**.
Sum of response durations: **897.3 s (14m 57.3s)**; median: 4.2 s (0m 4.2s).

## 7. Local llama.cpp per-model and per-task profile

| Model | Task | Requests | Pending | p50 HTTP | p95 HTTP | Prompt tokens | Completion tokens | Reasoning tokens | Length stops | Prefill p50 | Decode p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| story9b | choose_units | 1 | 0 | 147.2 s (2m 27.2s) | 147.2 s (2m 27.2s) | 1700.0 | 593.0 | 0 | 0 | 15730.887 ms | 131383.18 ms |
| story9b | credit_classifier | 2 | 1 | 132.3 s (2m 12.3s) | 132.3 s (2m 12.3s) | 687.0 | 556.0 | 0 | 0 | 9305.307 ms | 122778.217 ms |
| visual4b | scene_analysis | 70 | 0 | 4.4 s (0m 4.4s) | 5.6 s (0m 5.6s) | 141493.0 | 19426.0 | 0 | 0 | 1180.827 ms | 3194.197 ms |
| visual4b | semantic_boundary | 76 | 0 | 3.8 s (0m 3.8s) | 4.4 s (0m 4.4s) | 112738.0 | 18043.0 | 0 | 0 | 869.412 ms | 2908.633 ms |

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 5.1 s (0m 5.1s)
- visual4b / ok / GPU: 3.5 s (0m 3.5s)
- story9b / ok / GPU: 12.1 s (0m 12.1s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1539.5 s (25m 39.5s)**.
Slowest detailed production stage: **scene_analysis — 555.2 s (9m 15.2s)**.

Only fixed internal check/stage names and numeric measurements are published.
