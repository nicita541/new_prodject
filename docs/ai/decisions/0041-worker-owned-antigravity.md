# ADR-0041: worker-owned Antigravity exchange

Status: accepted, 2026-10-13. Supersedes default ownership in ADR-0028/0029 while preserving manual/external compatibility.

The user requires one explicit start through validated exports and explicitly chose to retain Antigravity. External-only ownership leaves correctly generated packets waiting indefinitely unless another process is started; replacing the stage with waiting_analysis also hides completed progress.

The existing fixed official-CLI script is now started and stopped by the job worker. This reuses tested packet isolation, strict image reception, schema/source validation and independent batching rather than duplicating a provider SDK. A separate always-running service would add orphan recovery and a second processing owner. Read APIs and catalog edits still never start inference.

Default configuration applies only when the per-job preference is absent. `{enabled:false}` remains manual; enabled-only remains external; `{enabled:true,managed:true}` is worker-owned. No provider/source packet identity changes, and accepted results stay reusable. The runner lock prevents duplicate coordinators. Fixed checked paths/arguments, a restricted existing persona, cooperative stop markers and the enclosing Windows Job Object constrain child processes. Unexpected runner exits surface immediately and preserve the log/checkpoints. Valid ERROR envelopes retain auth/quota/context/timeout categories even when the official CLI exits1; batch failures retain the actionable cause. Legacy generic process exits can be explained from saved envelopes without changing artifacts during reads. Credentials remain with the official installation.

Runner/result publications atomically rename with Windows MoveFileEx(REPLACE_EXISTING|WRITE_THROUGH), avoiding ReplaceFile destination ACL metadata copying. Only transient sharing/access errors have bounded local retries; they never repeat an inference. Waiting retains the canonical pipeline stage, with current-run evidence for legacy jobs.

Validation covers actual PowerShell queue overlap, cancellation, invalid/empty/output-limited responses, runner startup/stop and progress states, plus Studio controls. External auth, quotas, terms and semantic response errors remain observable constraints; the application neither bypasses them nor accepts invalid model answers.

Rollback: explicitly disable managed exchange or retain enabled-only external mode, then revert the worker-owned runner/UI changes. Existing artifacts and manual import remain readable; no destructive migration is required.
