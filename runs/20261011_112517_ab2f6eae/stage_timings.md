# KADR — complete verification timing

**Elapsed until reporting:** 2210.9 s (36m 50.9s)

This clock covers verification and model processing, but excludes the subsequent Git push.
A missing measurement means the test was recorded by an older launcher, not zero time.

## 1. Verification steps, in execution order (sequential)

| Step | Status | Duration | % of test |
| --- | --- | ---: | ---: |
| python_compile | PASS | 0.6 s (0m 0.6s) | 0.03% |
| python_dependencies | PASS | 1.3 s (0m 1.3s) | 0.06% |
| python_tests | PASS | 172.5 s (2m 52.5s) | 7.8% |
| react_tests | PASS | 28.0 s (0m 28.0s) | 1.27% |
| react_lint | PASS | 0.7 s (0m 0.7s) | 0.03% |
| react_build | PASS | 6.3 s (0m 6.3s) | 0.28% |
| ffmpeg | PASS | 0.0 s (0m 0.0s) | 0.0% |
| ffprobe | PASS | 0.0 s (0m 0.0s) | 0.0% |
| full_pipeline_3min | PASS | 51.9 s (0m 51.9s) | 2.35% |
| prepare_real_source | PASS | 7.3 s (0m 7.3s) | 0.33% |
| real_model_3min | TIMEOUT | 1932.6 s (32m 12.6s) | 87.41% |
| safe_ai_diagnostics | PASS | not measured | — |

## 2. Technical FFmpeg E2E substeps (inside full_pipeline_3min)

| Step | Status | Duration |
| --- | --- | ---: |
| generate_true_180_second_mp4 | passed | 0.7 s (0m 0.7s) |
| ffprobe_source_and_prepare_decision_fixture | passed | 0.0 s (0m 0.0s) |
| real_pipeline_plan_and_ffmpeg_render | passed | 38.1 s (0m 38.1s) |
| decode_validate_mp4_audio_srt_and_plan | passed | 0.1 s (0m 0.1s) |
| second_full_pipeline_run_for_cache | passed | 1.3 s (0m 1.3s) |
| invalidate_corrupted_subtitles_and_rerender | passed | 8.7 s (0m 8.7s) |
| ffmpeg_finishing_zoom_music_and_edited_captions | passed | 1.4 s (0m 1.4s) |
| real_studio_http_source_plan_mp4_srt_and_range | passed | 0.3 s (0m 0.3s) |

## 3. Real ASR/VLM + render acceptance substeps (inside real_model_3min)

| Step | Status | Duration |
| --- | --- | ---: |

## 4. Real production stages in first-seen order

| Stage | Completed calls | Unfinished | Inclusive time | % of production |
| --- | ---: | ---: | ---: | ---: |
| pipeline | 0 | 1 | not measured | — |
| prepare | 1 | 0 | 0.3 s (0m 0.3s) | — |
| transcribe | 1 | 0 | 21.5 s (0m 21.5s) | — |
| scenes | 1 | 0 | 418.9 s (6m 58.9s) | — |
| shot_detection | 1 | 0 | 1.5 s (0m 1.5s) | — |
| media_perception | 1 | 0 | 6.9 s (0m 6.9s) | — |
| scene_detection | 1 | 0 | 408.7 s (6m 48.7s) | — |
| semantic_boundary | 84 | 0 | 344.3 s (5m 44.3s) | — |
| analysis | 0 | 0 | not measured | — |
| analyze | 2 | 1 | 721.8 s (12m 1.8s) | — |
| scene_analysis | 31 | 0 | 498.8 s (8m 18.8s) | — |
| scene_recovery | 0 | 0 | not measured | — |
| story_refinement | 1 | 0 | 123.7 s (2m 3.7s) | — |
| condense | 1 | 0 | 282.5 s (4m 42.5s) | — |
| source_roles | 0 | 0 | not measured | — |
| global_visual_verification | 1 | 0 | 187.0 s (3m 7.0s) | — |
| selection_adjudication | 0 | 1 | not measured | — |

**Important:** production stage durations are INCLUSIVE and can overlap (e.g. pipeline contains scenes, and scenes contain semantic_boundary). Do not add their times or percentages. Stages terminated without an end event are marked unfinished and their actual execution time is NOT invented.

## 5. Planning / rendering for each production invocation

| Run | Status | Overall | Analysis | Planning | Part context | Rendering | Parts cached |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | running | not measured | not measured | not measured | not measured | not measured | 0/0 |

## 6. Model inference

Requests: **158**, responses: **158**, errors: **0**.
Sum of response durations: **632.9 s (10m 32.9s)**; median: 4.0 s (0m 4.0s).

## 7. Local llama.cpp per-model and per-task profile

### Total tokens used in this run (whole-run usage ledger)

**All providers combined: 947,488.00 tokens**.
These are actual provider-reported tokens for completed HTTP replies, not a prediction of the unfinished calls. Do NOT add the separate local-model breakdown again — it measures some of the same responses.

| Provider | Counted responses | Input tokens | Output tokens | Total tokens | Unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| local | 163 | 282205 | 43844 | 326049 | 0 |
| deepseek | 167 | 571435 | 50004 | 621439 | 0 |

### DeepSeek cache and API cost (reported usage only)

- API context-cache hit tokens: **82432**.
- API context-cache miss tokens: **489003**.
- Replies with validated cache breakdown: **167**.
- Estimated USD off-peak: **0.10**; peak: **0.21**.
- DeepSeek responses missing usage: **0**.
Note: the cost estimate excludes pending and unknown responses and is NOT a billing or balance guarantee.
KADR's full response cache costs $0; a DeepSeek context-cache hit is still billed.

### Average model cost: visual 4B versus story 9B

Average latency includes completed model requests only. Token averages count ONLY calls with usage data. Generation speed uses measured llama.cpp decode timing and token counts, not total network latency.

| Model | Completed / requested | Tokens measured / missing | Input total | Output total | Measured total | Avg input / call | Avg output / call | Avg total / call | Avg time / completed call | Decode tokens/s | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | 184/184 | 167/17 | 571435 | 50004 | 621439 | 3,421.77 | 299.43 | 3,721.19 | 2.6 s (0m 2.6s) | not measured | 3.8 s (0m 3.8s) |
| visual4b | 163/163 | 163/0 | 282205 | 43844 | 326049 | 1,731.32 | 268.98 | 2,000.30 | 4.1 s (0m 4.1s) | 82.71 | 5.6 s (0m 5.6s) |

### By task (choose_units, credit_classifier, scene_analysis, etc.)

| Model | Task | Calls (finished/pending) | Avg HTTP time | p95 HTTP | Avg input tok | Avg output tok | Decode tokens/s | Input tokens | Output tokens | Unknown tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepseek_flash | choose_units | 44/0 | 2.1 s (0m 2.1s) | 2.5 s (0m 2.5s) | 2,085.64 | 110.77 | not measured | 91768 | 4874 | 0 |
| deepseek_flash | credit_classifier | 3/0 | 1.7 s (0m 1.7s) | 2.0 s (0m 2.0s) | 814.00 | 31.00 | not measured | 2442 | 93 | 0 |
| deepseek_flash | story_refinement | 125/0 | 2.8 s (0m 2.8s) | 3.9 s (0m 3.9s) | 4,193.54 | 399.02 | not measured | 452902 | 43094 | 17 |
| deepseek_flash | verify_omissions | 12/0 | 2.1 s (0m 2.1s) | 2.8 s (0m 2.8s) | 2,026.92 | 161.92 | not measured | 24323 | 1943 | 0 |
| visual4b | scene_analysis | 62/0 | 4.7 s (0m 4.7s) | 5.6 s (0m 5.6s) | 2,047.18 | 305.11 | 85.27 | 126925 | 18917 | 0 |
| visual4b | semantic_boundary | 96/0 | 3.6 s (0m 3.6s) | 4.2 s (0m 4.2s) | 1,409.97 | 228.57 | 80.21 | 135357 | 21943 | 0 |
| visual4b | story_refinement | 5/0 | 8.7 s (0m 8.7s) | 9.6 s (0m 9.6s) | 3,984.60 | 596.80 | 86.11 | 19923 | 2984 | 0 |

The visual model corresponds to the configured Qwen visual GGUF (normally 4B; a configured 3B would require a matching alias update). The story model corresponds to the configured 9B GGUF.

**llama.cpp startup attempts:**

- visual4b / ok / GPU: 8.1 s (0m 8.1s)
- visual4b / ok / GPU: 4.1 s (0m 4.1s)
- visual4b / ok / GPU: 4.0 s (0m 4.0s)


## 8. Bottleneck candidates

Slowest verification step: **real_model_3min — 1932.6 s (32m 12.6s)**.
Slowest detailed production stage: **scene_analysis — 498.8 s (8m 18.8s)**.

Only fixed internal check/stage names and numeric measurements are published.
