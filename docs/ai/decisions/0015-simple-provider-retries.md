# 0015 — Provider requests without local monetary gating

2026-10-05. The user explicitly requested removal of economy mode and money counting: a failed request should retry twice and montage must be launchable.

The active provider no longer reads/writes spending ledgers, reserves charges or checks balance before analysis. Status and job launch depend on local key configuration and normal system readiness. Historical monetary files remain untouched and have no authority over current requests. Connection checking uses `/models`, not `/user/balance`.

Each query sends at most three requests. Network, HTTP and malformed/schema-invalid responses can retry; cancellation, authentication failures and certificate verification failures stop immediately. Successful answers remain cached by actual text, images, model and schema. Monetary response metadata is not required for a valid answer. An exhausted query reports the failure without globally disabling later episodes.

This supersedes the monetary launch/recovery requirements in earlier decisions and QA records. OP ownership, silent action, reaction preservation and export concurrency contracts remain in force. Rollback is a Git revert; no historical accounting data is deleted.
