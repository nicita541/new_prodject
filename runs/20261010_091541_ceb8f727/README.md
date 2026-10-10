# KADR verification report

- Run: 20261010_091541_ceb8f727
- Logs: [LOCAL_ONLY]
- Branch: codex/dramatic-montage
- Commit: 4e768ef8fe600d1c4f8e5f492c2c5363aa9e1259
- Profile: FULL WITH LOCAL AI
- Result: FAIL (passed 11; failed 1; skipped 0)
- Real ASR/VLM: REQUIRED, see real_model_3min

| Check | Result | Details |
| --- | --- | --- |
| python_compile | PASS |  |
| python_dependencies | PASS |  |
| python_tests | PASS | 1174 passed |
| react_tests | PASS |  |
| react_lint | PASS | 35 warnings, 0 errors |
| react_build | PASS |  |
| ffmpeg | PASS |  |
| ffprobe | PASS |  |
| full_pipeline_3min | PASS |  |
| prepare_real_source | PASS |  |
| real_model_3min | TIMEOUT | exceeded 1550 seconds; inspect local diagnostics |
| safe_ai_diagnostics | PASS | allowlisted AI metadata generated |

- AI diagnostics: ai_diagnostics.json (safe numeric and stage metadata)

Raw, unredacted logs remain on the user's computer.
