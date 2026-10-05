# Goal
Show provider-sourced balance observations and account balance decrease instead of presenting token-price ceilings as actual spending. Refresh during cloud work and expose update time.

# Current state
The ledger uses peak token prices and reservations. DeepSeek's documented public /user/balance reports USD/CNY balance, not invoice cost or per-key historical usage. The dashboard shown by the user has finer billing data outside this public contract. A worker is currently active and must not be interrupted for server deployment.

# Constraints
Preserve ledger/unknown-charge guards. User removed the $0.10 attempt cap. No dashboard credential extraction or undocumented billing scraping. Existing jobs without a baseline cannot gain a fabricated historical cost. Account changes are not necessarily this job's bill. All data stays in this workspace, keys never enter UI/logs.

# Implementation
1. Store independent validated balance snapshots and job/attempt measurement windows under settings. Capture first-request baseline and later provider balance. Separate account scope/partial coverage/adjustment/staleness from numeric decrease.
2. Expose cached status and throttled free refresh without taking the paid-request ledger lock. Add automatic/manual balance refresh UI, timestamps and truthful old-job fallback; keep budget ceilings separately labeled.
3. Test balances, failures, concurrency, old data, attempt isolation, ledger nonmutation, UI and API boundaries. Check a real free balance request; activate new backend after the current worker finishes.

# Validation
Mock response deltas differ from token-price estimates. Top-ups/unknown/missing or malformed USD are never zero-spend claims. Cached requests and old jobs retain accounting. Slow/failed balance requests never resend paid work or clear reservations. API/DOM show numeric provider values and keep errors/private fields out.

# Risks and rollback
Balance may lag billing; other clients/credit changes can affect it. Label account observations, not exact per-job invoices. Independent additive state and endpoints allow rollback without ledger migration. Do not stop an active worker for activation.

# Progress
- [x] Inspect provider contract and current accounting.
- [x] Implement snapshots, hooks and UI. Per-key usage is explicitly distinct; user declined dashboard login.
- [x] Verify mocked cases: 328 Python tests/120 subtests and 17 UI checks passed on continuation. Live free account check succeeded; recovery preserved all 987 existing cost entries.
- [x] Activate while idle and document account/per-key limits. Real browser shows attempt 4 account decrease, separately labeled token ceiling, timestamp and no amount cap/reset control.
