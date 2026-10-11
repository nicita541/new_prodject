# 0028: Explicit manual Antigravity exchange

Date: 2026-10-12. Status: accepted as temporary, opt-in transport.

Qwen9B semantic calls can be exported at the existing query/schema boundary. The user wants Google AI Pro through authorized official agy, with no API keys/proxies and no application wrapper around consumer CLI. KADR therefore exports immutable job-local packets and pauses the worker with `waiting_analysis`. An independently user-run PowerShell script invokes agy; importing an accepted JSON resumes the same job.

Only manual-provider 9B sessions are replaced. Whisper and initial local4B perception retain the native provider identity. Qwen and DeepSeek adapters remain unchanged. Packet identity includes source signature, exact prompt/schema, thinking/output budget and image hashes. Strict imports bind source scope and schema; native story coverage checks reject contradictory units. Existing downstream editorial validators retain authority.

Explicit local↔manual switching copies semantic checkpoints into provider banks and restores the requested bank. Factual video/audio/ASR/4B artifacts are neither deleted nor moved. No migration of existing jobs is required; local provider rollback remains available on stopped jobs. Completed exports cannot change provider.

Queries remain conditional: one accepted decision may generate another packet. There is no unbounded batch cloud execution or implicit retry. CLI failures preserve per-attempt diagnostic files, never manufacture a model answer. Runtime has no CLI dependency. Conservative context sizing avoids needing the 9B tokenizer but is not an actual Gemini token count.

Validation: strict JSON/schema/source/image/path tests, actual worker waiting-state test, API busy/cancel/retry/rollback tests, unchanged native-provider routing, frontend build and real Gemini image/context JSON accepted on a small existing job. Details and limitations: [user guide](../../antigravity-manual.md).
