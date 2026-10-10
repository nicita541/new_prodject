# KADR verification report

- Run: 20261010_101825_6a4da318
- Logs: [LOCAL_ONLY]
- Branch: codex/dramatic-montage
- Commit: fd3872d501b48a1b626933aac1601a1f4e6cd50f
- Profile: FULL WITH LOCAL AI
- Result: FAIL (passed 12; failed 1; skipped 0)
- Real ASR/VLM: REQUIRED, see real_model_3min

| Check | Result | Details |
| --- | --- | --- |
| python_compile | PASS |  |
| python_dependencies | PASS |  |
| python_tests | PASS | 1181 passed |
| react_tests | PASS |  |
| react_lint | PASS | 35 warnings, 0 errors |
| react_build | PASS |  |
| ffmpeg | PASS |  |
| ffprobe | PASS |  |
| full_pipeline_3min | PASS |  |
| prepare_real_source | PASS |  |
| real_model_3min | TIMEOUT | exceeded 1546 seconds; inspect local diagnostics |
| safe_ai_diagnostics | PASS | allowlisted AI metadata generated |
| stage_timings | PASS | full timing breakdown generated |

- AI diagnostics: ai_diagnostics.json (safe numeric and stage metadata)

- Stage timings: stage_timings.md and stage_timings.json (safe wall-clock and nested breakdown)

Raw, unredacted logs remain on the user's computer.
