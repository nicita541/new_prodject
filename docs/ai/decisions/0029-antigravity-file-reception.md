# 0029: Opt-in automatic reception of independently produced CLI files

Date: 2026-10-12. Status: implemented, consumer-plan compatibility not certified.

The user requested removal of packet-by-packet import/retry while retaining their separately installed official agy and Google AI Pro. KADR never invokes CLI. A separately user-started direct script watches only the current exported query and publishes a complete JSON file atomically. Opt-in ManualVision waits for the file in the same worker and uses the existing import validators. This avoids replaying pipeline stages and loading local perception sessions after every semantic answer.

Google FAQ allows direct scripting/CI and excludes wrapping CLI inside third-party applications under consumer plans. Separate installation is not an automatic exemption. The FAQ does not explicitly certify this end-to-end file workflow. No OAuth extraction, proxies, account switching or unsupported authentication paths are introduced.

Manual behavior remains the default for existing jobs. automation.json is an opt-in presentation/transport setting, not model identity; accepted results retain their original content hashes. exchange.json identifies the only current request; worker startup clears stale exchange status. runner.lock prevents two separate scripts processing the same job. runner.json exposes separate execution state. Responses are bounded and validated before downstream editorial checks. Cancellation/timeouts/errors retain checkpoints and never turn missing/invalid model output into an answer. CLI time budget and pipeline completion time are separate.

Rollback: stop the job, disable auto-import, keep manual import or switch back to Qwen through the existing checkpoint bank. Native Qwen/DeepSeek routing, video algorithms and editorial gates remain. ASR progress sidecar is optional and bound to the diagnostic run identity; UI uses per-stage counters exclusively.
