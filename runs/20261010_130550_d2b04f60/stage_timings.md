# KADR — complete verification timing

**Elapsed until reporting:** 2206.7 s (36m 46.7s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.4 s (0m 0.4s) | 0.02% |
| python_dependencies | PASS | 0.7 s (0m 0.7s) | 0.03% |
| python_tests | PASS | 137.7 s (2m 17.7s) | 6.24% |
| react_tests | PASS | 6.7 s (0m 6.7s) | 0.3% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.5 s (0m 2.5s) | 0.11% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 94.0 s (1m 34.0s) | 4.26% |
| prepare_real_source | PASS | 10.8 s (0m 10.8s) | 0.49% |
| real_model_3min | TIMEOUT | 1947.7 s (32m 27.7s) | 88.26% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.6 s (0m 0.6s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 80.9 s (1m 20.9s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.2 s (0m 1.2s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.6 s (0m 8.6s) |
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
| transcribe | 1 | 0 | 29.1 s (0m 29.1s) | — |
| scenes | 1 | 0 | 346.6 s (5m 46.6s) | — |
| shot_detection | 1 | 0 | 2.5 s (0m 2.5s) | — |
| media_perception | 1 | 0 | 6.7 s (0m 6.7s) | — |
| scene_detection | 1 | 0 | 335.8 s (5m 35.8s) | — |
| semantic_boundary | 74 | 0 | 279.6 s (4m 39.6s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 1 | 0 | 794.3 s (13m 14.3s) | — |
| scene_analysis | 20 | 0 | 579.2 s (9m 39.2s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 0 | 1 | not measured | — |
| condense | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **153**, responses: **152**, errors: **1**.
Sum of response durations: **1372.3 s (22m 52.3s)**; median: 4.0 s (0m 4.0s).

## 7. Local llama.cpp per-model and per-task profile

### Total tokens used in this run (whole-run usage ledger)

**All providers combined: 309,306.00 tokens**.
These are actual provider-reported tokens for completed HTTP replies, not a prediction of the unfinished calls. Do NOT add the separate local-model breakdown again — it measures some of the same responses.

| Provider | Counted responses | Input tokens | Output tokens | Total tokens | Unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| local | 151 | 269245 | 40061 | 309306 | 0 |
| deepseek | 0 | 0 | 0 | 0 | 0 |

### Average model cost: visual 4B versus story 9B

Average latency includes completed model requests only. Token averages count ONLY calls with usage data. Generation speed uses measured llama.cpp decode timing and token counts, not total network latency.

| Model | Completed / requested | Tokens measured / missing | Input total | Output total | Measured total | Avg input / call | Avg output / call | Avg total / call | Avg time / completed call | Decode tokens/s | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| story9b | 4/5 | 3/2 | 6563 | 1925 | 8488 | 2,187.67 | 641.67 | 2,829.33 | 190.0 s (3m 10.0s) | 4.23 | 240.2 s (4m 0.2s) |
| visual4b | 148/148 | 148/0 | 262682 | 38136 | 300818 | 1,774.88 | 257.68 | 2,032.55 | 4.1 s (0m 4.1s) | 84.73 | 5.2 s (0m 5.2s) |

### By task (choose_units, credit_classifier, scene_analysis, etc.)

| Model | Task | Calls (finished/pending) | Avg HTTP time | p95 HTTP | Avg input tok | Avg output tok | Decode tokens/s | Input tokens | Output tokens | Unknown tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| story9b | choose_units | 3/1 | 173.3 s (2m 53.3s) | 185.8 s (3m 5.8s) | 2,187.67 | 641.67 | 4.23 | 6563 | 1925 | 1 |
| story9b | verify_omissions | 1/0 | 240.2 s (4m 0.2s) | 240.2 s (4m 0.2s) | not measured | not measured | not measured | 0 | 0 | 1 |
| visual4b | scene_analysis | 72/0 | 4.6 s (0m 4.6s) | 5.4 s (0m 5.4s) | 2,082.57 | 285.61 | 87.77 | 149945 | 20564 | 0 |
| visual4b | semantic_boundary | 76/0 | 3.7 s (0m 3.7s) | 4.4 s (0m 4.4s) | 1,483.38 | 231.21 | 81.43 | 112737 | 17572 | 0 |

The visual model corresponds to the configured Qwen visual GGUF (normally 4B; a configured 3B would require a matching alias update). The story model corresponds to the configured 9B GGUF.

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 5.0 s (0m 5.0s)
- visual4b / ok / GPU: 3.5 s (0m 3.5s)
- story9b / ok / GPU: 5.6 s (0m 5.6s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1947.7 s (32m 27.7s)**.
Slowest detailed production stage: **scene_analysis — 579.2 s (9m 39.2s)**.

Only fixed internal check/stage names and numeric measurements are published.
