# Goal
Add an optional DeepSeek analysis provider with verified account-balance checks, cautious token limits and persistent usage accounting while the user has approximately USD 0.06 available. Preserve the default fully local workflow and all files inside F:\new_prodject. The initial coordinator-imposed USD 0.01 total ceiling was rejected by the user and removed; no default application-wide ceiling is active.

# Current state
Local models implement query(prompt, image, max_tokens, schema) and token_count(). Analysis and individual stage caches include model/profile identity. The user explicitly supplied an API key and authorized cautious use. Official documentation currently lists deepseek-flash vision, JSON output, GET /models and GET /user/balance; peak rates are USD 0.30/M input and USD 1.20/M output.

# Constraints
No secrets in source, public API, logs or diagnostics. Private key lives under ignored data/settings. Only api.deepseek.com HTTPS is allowed; disable redirects/proxies. No paid automatic retries. Verify available account funds before a request and persist a conservative reservation before sending it; failures with unknown billing retain the reservation and halt further paid calls. The public balance is the latest checked snapshot, not continuous remote monitoring. Account top-ups are recognized by free balance checks. Other clients can spend the same account.

# Implementation
1. Add stdlib HTTP client, sanitized balance/model checks, content-addressed response cache, schema checks and durable USD ledger.
2. Add an explicit job provider choice, safe status/check API and Russian UI disclosure of remote text/frame processing. Local remains default.
3. Include provider identity in analysis cache keys and use the selected provider through the existing sequential model interface.
4. Run no-cost tests of budget reservation, restart/concurrency, uncertain failures, cancellation, cache reuse, secret redaction and local compatibility.
5. Check actual account/model availability and run at most three short framing diagnostics. Record actual usage and balance without the key. Keep full paid episode analysis deferred; explain its estimated cost.

# Validation
Provider unit tests and existing full test suite; safe UI/API provider choice. Actual paid diagnostic only after balance and accounting checks work. Full paid episode analysis is not part of the initial three-sample experiment.

# Risks and rollback
Provider/model and rates can change, JSON can be wrong, cancellation cannot undo an accepted billable request. Leave unknown reservations charged at their maximum and fail closed. Disable API analysis by choosing local; retain prior outputs and checkpoints. No global client/Codex configuration changes.

# Progress
- [x] Client and budget/cache.
- [x] API/UI and pipeline integration.
- [x] Tests and actual limited diagnostic.

# Observed validation
GET balance/models confirmed USD 0.06 and deepseek-flash image support. Three actual requests at source times 42.2, 352.1 and 197.78 returned valid schema-constrained focus in 2.266, 2.235 and 2.375 seconds. Peak-rate cost ceiling from reported usage totals USD 0.0008502; this is a conservative tariff estimate, not a claimed exact account debit. The API still reports USD 0.06. Photos under first job diagnostics/deepseek-f1d21388 show improved face framing and gesture visibility compared with previous 4B crops. The same three requests repeated with --cache-only in diagnostics/deepseek-355079eb, without network or additional ledger charges. Full paid episode analysis was not started. Root ran 197 tests and 59 subtests in 15.73s before adding the cache-only guard; that guard passed its new test in the 27-test provider subset.

After removing the unrequested total ceiling, root ran all 199 tests and 59 subtests in 16.28s. A fake-account test verifies accumulated usage can exceed USD 0.01 while valid funds remain; insufficient verified funds prevent a paid POST. Live local status shows budget_usd=null, last balance USD 0.06 and unchanged charged estimate USD 0.0008502. The local full review continued after a checkpointed server reload.
