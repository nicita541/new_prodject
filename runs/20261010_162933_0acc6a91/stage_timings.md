# KADR — complete verification timing

**Elapsed until reporting:** 2209.3 s (36m 49.3s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.5 s (0m 0.5s) | 0.02% |
| python_dependencies | PASS | 0.7 s (0m 0.7s) | 0.03% |
| python_tests | PASS | 141.8 s (2m 21.8s) | 6.42% |
| react_tests | PASS | 7.4 s (0m 7.4s) | 0.34% |
| react_lint | PASS | 0.4 s (0m 0.4s) | 0.02% |
| react_build | PASS | 2.7 s (0m 2.7s) | 0.12% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 89.2 s (1m 29.2s) | 4.04% |
| prepare_real_source | PASS | 11.3 s (0m 11.3s) | 0.51% |
| real_model_3min | TIMEOUT | 1947.6 s (32m 27.6s) | 88.16% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.7 s (0m 0.7s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 75.8 s (1m 15.8s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.3 s (0m 1.3s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.8 s (0m 8.8s) |
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
| transcribe | 1 | 0 | 29.9 s (0m 29.9s) | — |
| scenes | 1 | 0 | 364.3 s (6m 4.3s) | — |
| shot_detection | 1 | 0 | 2.7 s (0m 2.7s) | — |
| media_perception | 1 | 0 | 6.8 s (0m 6.8s) | — |
| scene_detection | 1 | 0 | 353.1 s (5m 53.1s) | — |
| semantic_boundary | 74 | 0 | 295.4 s (4m 55.4s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 2 | 0 | 777.7 s (12m 57.7s) | — |
| scene_analysis | 16 | 0 | 583.8 s (9m 43.8s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 1 | 0 | 164.5 s (2m 44.5s) | — |
| condense | 1 | 0 | 412.1 s (6m 52.1s) | — |
| source_roles | 0 | 0 | not measured | — |
| global_visual_verification | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **147**, responses: **147**, errors: **0**.
Sum of response durations: **641.9 s (10m 41.9s)**; median: 4.2 s (0m 4.2s).

## 7. Local llama.cpp per-model and per-task profile

### Total tokens used in this run (whole-run usage ledger)

**All providers combined: 705,442.00 tokens**.
These are actual provider-reported tokens for completed HTTP replies, not a prediction of the unfinished calls. Do NOT add the separate local-model breakdown again — it measures some of the same responses.

| Provider | Counted responses | Input tokens | Output tokens | Total tokens | Unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| local | 247 | 603795 | 66750 | 670545 | 0 |
| deepseek | 20 | 33336 | 1561 | 34897 | 0 |

### DeepSeek cache and API cost (reported usage only)

- API context-cache hit tokens: **6144**.
- API context-cache miss tokens: **27192**.
- Replies with validated cache breakdown: **20**.
- Estimated USD off-peak: **0.01**; peak: **0.01**.
- DeepSeek responses missing usage: **0**.
Note: the cost estimate excludes pending and unknown responses and is NOT a billing or balance guarantee.
KADR's full response cache costs $0; a DeepSeek context-cache hit is still billed.

### Average model cost: visual 4B versus story 9B

Average latency includes completed model requests only. Token averages count ONLY calls with usage data. Generation speed uses measured llama.cpp decode timing and token counts, not total network latency.

| Model | Completed / requested | Tokens measured / missing | Input total | Output total | Measured total | Avg input / call | Avg output / call | Avg total / call | Avg time / completed call | Decode tokens/s | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | 20/20 | 20/0 | 33336 | 1561 | 34897 | 1,666.80 | 78.05 | 1,744.85 | 1.9 s (0m 1.9s) | not measured | 2.2 s (0m 2.2s) |
| visual4b | 249/250 | 247/3 | 603795 | 66750 | 670545 | 2,444.51 | 270.24 | 2,714.76 | 4.9 s (0m 4.9s) | 84.39 | 11.2 s (0m 11.2s) |

### By task (choose_units, credit_classifier, scene_analysis, etc.)

| Model | Task | Calls (finished/pending) | Avg HTTP time | p95 HTTP | Avg input tok | Avg output tok | Decode tokens/s | Input tokens | Output tokens | Unknown tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | choose_units | 8/0 | 1.9 s (0m 1.9s) | 2.0 s (0m 2.0s) | 2,099.38 | 90.38 | not measured | 16795 | 723 | 0 |
| deepseek_flash | credit_classifier | 5/0 | 1.7 s (0m 1.7s) | 2.2 s (0m 2.2s) | 846.00 | 31.00 | not measured | 4230 | 155 | 0 |
| deepseek_flash | story_refinement | 3/0 | 1.9 s (0m 1.9s) | 2.1 s (0m 2.1s) | 1,392.33 | 25.00 | not measured | 4177 | 75 | 0 |
| deepseek_flash | verify_omissions | 4/0 | 2.2 s (0m 2.2s) | 2.5 s (0m 2.5s) | 2,033.50 | 152.00 | not measured | 8134 | 608 | 0 |
| visual4b | choose_units | 47/0 | 2.5 s (0m 2.5s) | 3.2 s (0m 3.2s) | 2,123.36 | 99.11 | 95.41 | 99798 | 4658 | 0 |
| visual4b | scene_analysis | 71/0 | 4.9 s (0m 4.9s) | 6.2 s (0m 6.2s) | 2,016.37 | 284.59 | 86.99 | 143162 | 20206 | 0 |
| visual4b | semantic_boundary | 76/0 | 3.9 s (0m 3.9s) | 4.4 s (0m 4.4s) | 1,483.49 | 230.99 | 78.44 | 112745 | 17555 | 0 |
| visual4b | story_refinement | 54/1 | 8.3 s (0m 8.3s) | 12.6 s (0m 12.6s) | 4,725.50 | 460.75 | 85.03 | 245726 | 23959 | 3 |
| visual4b | verify_omissions | 1/0 | 6.2 s (0m 6.2s) | 6.2 s (0m 6.2s) | 2,364.00 | 372.00 | 87.34 | 2364 | 372 | 0 |

The visual model corresponds to the configured Qwen visual GGUF (normally 4B; a configured 3B would require a matching alias update). The story model corresponds to the configured 9B GGUF.

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 6.6 s (0m 6.6s)
- visual4b / ok / GPU: 3.5 s (0m 3.5s)
- visual4b / ok / GPU: 4.0 s (0m 4.0s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1947.6 s (32m 27.6s)**.
Slowest detailed production stage: **scene_analysis — 583.8 s (9m 43.8s)**.

Only fixed internal check/stage names and numeric measurements are published.
