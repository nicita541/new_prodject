# Manual Antigravity CLI exchange

## Goal
Add an explicit temporary manual provider replacing Qwen9B queries with immutable job-local packets and imported official agy JSON, retaining local4B perception, ASR, validators and rendering. Users run CLI themselves; KADR never launches it or extracts credentials.

## Current state
LocalVision.query(prompt, images, max_tokens, schema, thinking_override) is the common 9B boundary. analysis orchestrates story selection, omission/credit/title/closing/source-role/global checks, pacing/editorial recovery and portrait focus. Existing stage caches include model identity/cache_profile. User branch is codex/dramatic-montage with prior cleanup/audit changes uncommitted.

## Constraints
Do not modify Qwen/DeepSeek clients, scene detection, FFmpeg/subtitles/renderer. No full episode processing. Preserve factual ASR/shot/scene/visual caches and provider-specific semantic checkpoints. Manual transport validates strict JSON/schema and source scope, then existing semantic validators remain authoritative. User explicitly permits existing agy profile on C; all KADR packets/output/log arguments remain F. No credential copying, keys/proxies, account rotation or automatic CLI inside application.

## Implementation
1. Verify installed CLI version/help and official headless contract; map 9B tasks.
2. Implement deterministic packet export/import session and intentional waiting status.
3. Route only new manual provider 9B to exchange; keep early local perception cache identity unchanged; preserve semantic checkpoints when switching provider.
4. Add API and controls to existing Studio, plus user-run script with bounded single-packet processing and official JSON/schema flags.
5. Verify schema/timestamp/path/context/cache/cancel/resume boundaries, Qwen/DeepSeek regressions, frontend build and actual UI. Prepare short real-data test; distinguish imported fixture from real Gemini inference and record actual reported usage.
6. Document operation, limitations and rollback; return exact HEAD SHA without implying uncommitted work is committed.

## Validation
Existing pytest and portable frontend test/lint/build commands; focused real API/UI checks; actual CLI --version/--help. Real cloud test uses separate user-run script because Google AI Pro excludes third-party application wrappers. Output envelope SUCCESS/structured_output and reported usage required; no invented token count or speed.

## Risks and rollback
Conditional queries require several prepare/import/resume cycles; packets cannot precompute unseen decisions. Image files and text go to Gemini only on explicit user script execution. Schema validity does not prove narrative correctness. Revert provider to local on the same stopped job; copied semantic cache bank protects prior Qwen work. Source signatures prevent stale packet reuse.

## Progress
- [x] Installed agy1.3.3 verified; official docs and 9B boundaries inspected.
- [x] Exchange implementation and provider routing.
- [x] Existing Studio controls and standalone script.
- [x] Integration/regression/manual verification: real Gemini image/context response imported; native analysis consumed it with zero repeated4B calls, then paused at the next dependent request. Actual Studio smoke import and local rollback passed. 108 focused tests/8 subtests, full1286 Python+133 React checks and final frontend build passed.
- [x] Documentation and results in docs/antigravity-manual.md and ADR0028. Whole-series editorial/cloud timing acceptance remains outside this small test.

## Observed corrections
File-read headless attempts returned SUCCESS with empty response and no structured_output; these were rejected. Windows PowerShell5 stripped quoted Russian arguments when text was inlined; explicit ProcessStartInfo Windows argument escaping fixed this. Gemini3.8FlashHigh produced valid real JSON in90.241s (CLI total43939 tokens); schema/source/unit coverage passed. Native cached continuation took10.347s with one imported response and no native4B queries. Prior Qwen checkpoints/settings were restored after the isolated test.
