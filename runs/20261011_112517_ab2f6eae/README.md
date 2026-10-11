# KADR verification report

- Run: 20261011_112517_ab2f6eae
- Logs: [LOCAL_ONLY]
- Branch: codex/dramatic-montage
- Commit: 0d751072f554e233baef25fd3509261528608ff9
- Profile: FULL WITH LOCAL WHISPER/QWEN4B + DEEPSEEK FLASH STORY
- Result: FAIL (passed 13; failed 1; skipped 0)
- Real ASR/VLM: REQUIRED, see real_model_3min

| Check | Result | Details |
| --- | --- | --- |
| python_compile | PASS |  |
| python_dependencies | PASS |  |
| python_tests | PASS | 1235 passed |
| react_tests | PASS |  |
| react_lint | PASS | 35 warnings, 0 errors |
| react_build | PASS |  |
| ffmpeg | PASS |  |
| ffprobe | PASS |  |
| full_pipeline_3min | PASS |  |
| deepseek_key_preflight | PASS |  |
| prepare_real_source | PASS |  |
| real_model_3min | TIMEOUT | exceeded 1930 seconds; inspect local diagnostics |
| safe_ai_diagnostics | PASS | allowlisted AI metadata generated |
| stage_timings | PASS | full timing breakdown generated |

- AI diagnostics: ai_diagnostics.json (safe numeric and stage metadata)

- Stage timings: stage_timings.md and stage_timings.json (safe wall-clock and nested breakdown)

Raw, unredacted logs remain on the user's computer.
