# KADR — complete verification timing

**Elapsed until reporting:** 2210.4 s (36m 50.4s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.4 s (0m 0.4s) | 0.02% |
| python_dependencies | PASS | 0.7 s (0m 0.7s) | 0.03% |
| python_tests | PASS | 139.7 s (2m 19.7s) | 6.32% |
| react_tests | PASS | 7.0 s (0m 7.0s) | 0.31% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.7 s (0m 2.7s) | 0.12% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 88.3 s (1m 28.3s) | 3.99% |
| prepare_real_source | PASS | 11.0 s (0m 11.0s) | 0.5% |
| real_model_3min | TIMEOUT | 1950.7 s (32m 30.7s) | 88.25% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.6 s (0m 0.6s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 75.0 s (1m 15.0s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.3 s (0m 1.3s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.7 s (0m 8.7s) |
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
| transcribe | 1 | 0 | 29.6 s (0m 29.6s) | — |
| scenes | 1 | 0 | 376.3 s (6m 16.3s) | — |
| shot_detection | 1 | 0 | 2.5 s (0m 2.5s) | — |
| media_perception | 1 | 0 | 6.8 s (0m 6.8s) | — |
| scene_detection | 1 | 0 | 365.4 s (6m 5.4s) | — |
| semantic_boundary | 74 | 0 | 305.0 s (5m 5.0s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 1 | 0 | 781.0 s (13m 1.0s) | — |
| scene_analysis | 20 | 0 | 570.4 s (9m 30.4s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 0 | 1 | not measured | — |
| condense | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **148**, responses: **148**, errors: **0**.
Sum of response durations: **630.4 s (10m 30.4s)**; median: 4.2 s (0m 4.2s).

## 7. Local llama.cpp per-model and per-task profile

### Total tokens used in this run (whole-run usage ledger)

**All providers combined: 323,469.00 tokens**.
These are actual provider-reported tokens for completed HTTP replies, not a prediction of the unfinished calls. Do NOT add the separate local-model breakdown again — it measures some of the same responses.

| Provider | Counted responses | Input tokens | Output tokens | Total tokens | Unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| local | 152 | 264685 | 40212 | 304897 | 0 |
| deepseek | 8 | 17518 | 1054 | 18572 | 0 |

### DeepSeek cache and API cost (reported usage only)

- API context-cache hit tokens: **2816**.
- API context-cache miss tokens: **14702**.
- Replies with validated cache breakdown: **8**.
- Estimated USD off-peak: **0.00**; peak: **0.01**.
- DeepSeek responses missing usage: **0**.
Note: the cost estimate excludes pending and unknown responses and is NOT a billing or balance guarantee.
KADR's full response cache costs $0; a DeepSeek context-cache hit is still billed.

### Average model cost: visual 4B versus story 9B

Average latency includes completed model requests only. Token averages count ONLY calls with usage data. Generation speed uses measured llama.cpp decode timing and token counts, not total network latency.

| Model | Completed / requested | Tokens measured / missing | Input total | Output total | Measured total | Avg input / call | Avg output / call | Avg total / call | Avg time / completed call | Decode tokens/s | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | 8/8 | 8/0 | 17518 | 1054 | 18572 | 2,189.75 | 131.75 | 2,321.50 | 2.3 s (0m 2.3s) | not measured | 2.7 s (0m 2.7s) |
| story9b | 4/5 | 4/1 | 7232 | 2429 | 9661 | 1,808.00 | 607.25 | 2,415.25 | 162.1 s (2m 42.1s) | 4.25 | 176.8 s (2m 56.8s) |
| visual4b | 148/148 | 148/0 | 257453 | 37783 | 295236 | 1,739.55 | 255.29 | 1,994.84 | 4.3 s (0m 4.3s) | 83.23 | 5.2 s (0m 5.2s) |

### By task (choose_units, credit_classifier, scene_analysis, etc.)

| Model | Task | Calls (finished/pending) | Avg HTTP time | p95 HTTP | Avg input tok | Avg output tok | Decode tokens/s | Input tokens | Output tokens | Unknown tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | choose_units | 4/0 | 2.2 s (0m 2.2s) | 2.3 s (0m 2.3s) | 2,461.75 | 108.25 | not measured | 9847 | 433 | 0 |
| deepseek_flash | credit_classifier | 1/0 | 2.0 s (0m 2.0s) | 2.0 s (0m 2.0s) | 774.00 | 27.00 | not measured | 774 | 27 | 0 |
| deepseek_flash | verify_omissions | 3/0 | 2.6 s (0m 2.6s) | 2.7 s (0m 2.7s) | 2,299.00 | 198.00 | not measured | 6897 | 594 | 0 |
| story9b | choose_units | 3/1 | 168.4 s (2m 48.4s) | 176.8 s (2m 56.8s) | 2,111.67 | 624.33 | 4.24 | 6335 | 1873 | 1 |
| story9b | credit_classifier | 1/0 | 143.3 s (2m 23.3s) | 143.3 s (2m 23.3s) | 897.00 | 556.00 | 4.26 | 897 | 556 | 0 |
| visual4b | scene_analysis | 72/0 | 4.5 s (0m 4.5s) | 5.4 s (0m 5.4s) | 2,011.35 | 276.25 | 86.42 | 144817 | 19890 | 0 |
| visual4b | semantic_boundary | 76/0 | 4.0 s (0m 4.0s) | 4.6 s (0m 4.6s) | 1,482.05 | 235.43 | 79.96 | 112636 | 17893 | 0 |

The visual model corresponds to the configured Qwen visual GGUF (normally 4B; a configured 3B would require a matching alias update). The story model corresponds to the configured 9B GGUF.

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 8.6 s (0m 8.6s)
- visual4b / ok / GPU: 4.0 s (0m 4.0s)
- story9b / ok / GPU: 16.1 s (0m 16.1s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1950.7 s (32m 30.7s)**.
Slowest detailed production stage: **scene_analysis — 570.4 s (9m 30.4s)**.

Only fixed internal check/stage names and numeric measurements are published.
