# KADR — complete verification timing

**Elapsed until reporting:** 1751.9 s (29m 11.9s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.2 s (0m 0.2s) | 0.01% |
| python_dependencies | PASS | 0.6 s (0m 0.6s) | 0.03% |
| python_tests | PASS | 139.0 s (2m 19.0s) | 7.93% |
| react_tests | PASS | 6.8 s (0m 6.8s) | 0.39% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.6 s (0m 2.6s) | 0.15% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 86.4 s (1m 26.4s) | 4.93% |
| prepare_real_source | PASS | 6.8 s (0m 6.8s) | 0.39% |
| real_model_3min | FAIL | 1472.6 s (24m 32.6s) | 84.06% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.6 s (0m 0.6s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 73.3 s (1m 13.3s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.2 s (0m 1.2s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.6 s (0m 8.6s) |
| ffmpeg_finishing_zoom_music_and_edited_captions | passed | 1.5 s (0m 1.5s) |
| real_studio_http_source_plan_mp4_srt_and_range | passed | 0.2 s (0m 0.2s) |

## 3. Real ASR/VLM + render acceptance substeps (inside real_model_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| genuine_production_analysis_to_final_mp4 | failed | 1472.3 s (24m 32.3s) |

## 4. Real production stages in first-seen order

| Stage | Completed calls | Unfinished | Inclusive time | % of production |
| --- | ---: | ---: | ---: | ---: |
| pipeline | 1 | 0 | 1471.1 s (24m 31.1s) | 99.96% |
| prepare | 1 | 0 | 0.3 s (0m 0.3s) | 0.02% |
| transcribe | 1 | 0 | 20.3 s (0m 20.3s) | 1.38% |
| scenes | 1 | 0 | 559.7 s (9m 19.7s) | 38.03% |
| shot_detection | 1 | 0 | 1.5 s (0m 1.5s) | 0.1% |
| media_perception | 1 | 0 | 6.1 s (0m 6.1s) | 0.42% |
| scene_detection | 1 | 0 | 550.5 s (9m 10.5s) | 37.4% |
| semantic_boundary | 84 | 0 | 487.6 s (8m 7.6s) | 33.13% |
| analysis | 0 | 0 | not measured | — |
| analyze | 1 | 0 | 743.4 s (12m 23.4s) | 50.51% |
| scene_analysis | 33 | 0 | 513.2 s (8m 33.2s) | 34.87% |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 1 | 0 | 146.8 s (2m 26.8s) | 9.97% |
| condense | 1 | 0 | 146.6 s (2m 26.6s) | 9.96% |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | failed | 1471.1 s (24m 31.1s) | 1470.4 s (24m 30.4s) | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **159**, responses: **159**, errors: **0**.
Sum of response durations: **792.5 s (13m 12.5s)**; median: 5.0 s (0m 5.0s).

## 7. Local llama.cpp per-model and per-task profile

### Total tokens used in this run (whole-run usage ledger)

**All providers combined: 453,634.00 tokens**.
These are actual provider-reported tokens for completed HTTP replies, not a prediction of the unfinished calls. Do NOT add the separate local-model breakdown again — it measures some of the same responses.

| Provider | Counted responses | Input tokens | Output tokens | Total tokens | Unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| local | 159 | 262224 | 41576 | 303800 | 0 |
| deepseek | 78 | 142216 | 7618 | 149834 | 0 |

### DeepSeek cache and API cost (reported usage only)

- API context-cache hit tokens: **27648**.
- API context-cache miss tokens: **114568**.
- Replies with validated cache breakdown: **78**.
- Estimated USD off-peak: **0.02**; peak: **0.04**.
- DeepSeek responses missing usage: **0**.
Note: the cost estimate excludes pending and unknown responses and is NOT a billing or balance guarantee.
KADR's full response cache costs $0; a DeepSeek context-cache hit is still billed.

### Average model cost: visual 4B versus story 9B

Average latency includes completed model requests only. Token averages count ONLY calls with usage data. Generation speed uses measured llama.cpp decode timing and token counts, not total network latency.

| Model | Completed / requested | Tokens measured / missing | Input total | Output total | Measured total | Avg input / call | Avg output / call | Avg total / call | Avg time / completed call | Decode tokens/s | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | 78/78 | 78/0 | 142216 | 7618 | 149834 | 1,823.28 | 97.67 | 1,920.95 | 1.9 s (0m 1.9s) | not measured | 2.3 s (0m 2.3s) |
| visual4b | 159/159 | 159/0 | 262224 | 41576 | 303800 | 1,649.21 | 261.48 | 1,910.69 | 5.0 s (0m 5.0s) | 85.19 | 5.8 s (0m 5.8s) |

### By task (choose_units, credit_classifier, scene_analysis, etc.)

| Model | Task | Calls (finished/pending) | Avg HTTP time | p95 HTTP | Avg input tok | Avg output tok | Decode tokens/s | Input tokens | Output tokens | Unknown tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | choose_units | 50/0 | 1.9 s (0m 1.9s) | 2.3 s (0m 2.3s) | 2,103.84 | 105.94 | not measured | 105192 | 5297 | 0 |
| deepseek_flash | credit_classifier | 18/0 | 1.6 s (0m 1.6s) | 2.0 s (0m 2.0s) | 874.00 | 31.00 | not measured | 15732 | 558 | 0 |
| deepseek_flash | verify_omissions | 10/0 | 2.1 s (0m 2.1s) | 2.3 s (0m 2.3s) | 2,129.20 | 176.30 | not measured | 21292 | 1763 | 0 |
| visual4b | scene_analysis | 63/0 | 4.9 s (0m 4.9s) | 5.6 s (0m 5.6s) | 2,011.48 | 300.11 | 87.66 | 126723 | 18907 | 0 |
| visual4b | semantic_boundary | 96/0 | 5.1 s (0m 5.1s) | 5.8 s (0m 5.8s) | 1,411.47 | 236.13 | 83.23 | 135501 | 22669 | 0 |

The visual model corresponds to the configured Qwen visual GGUF (normally 4B; a configured 3B would require a matching alias update). The story model corresponds to the configured 9B GGUF.

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 5.1 s (0m 5.1s)
- visual4b / ok / GPU: 3.5 s (0m 3.5s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1472.6 s (24m 32.6s)**.
Slowest detailed production stage: **scene_analysis — 513.2 s (8m 33.2s)**.

Only fixed internal check/stage names and numeric measurements are published.
