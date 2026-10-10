# KADR verification report

- Run: 20261010_083318_4e6e59c9
- Logs: [LOCAL_ONLY]
- Branch: codex/dramatic-montage
- Commit: 1513449e689a57d7e993b8a4b182cc35562b2849
- Profile: FULL WITH LOCAL AI
- Result: FAIL (passed 10; failed 1; skipped 0) — corrected after reconciliation with e2e_overview.json
- Real ASR/VLM: REQUIRED, see real_model_3min

| Check | Result | Details |
| --- | --- | --- |
| python_compile | PASS |  |
| python_dependencies | PASS |  |
| python_tests | PASS | 1167 passed |
| react_tests | PASS |  |
| react_lint | PASS | 35 warnings, 0 errors |
| react_build | PASS |  |
| ffmpeg | PASS |  |
| ffprobe | PASS |  |
| full_pipeline_3min | PASS |  |
| prepare_real_source | PASS |  |
| real_model_3min | FAIL | Authoritative E2E artifact failed after 540.609s; original launcher reported PASS incorrectly |

Raw, unredacted logs remain on the user's computer.

## Post-run correction

This run's original Windows wrapper reported PASS for `real_model_3min` despite its own `e2e_overview.json` recording `failed`. The outcome is corrected to FAIL without altering the original exit code. This correction does **not** imply a fresh test run. The local source/model logs are needed to identify the underlying error.
