# Known provider quota resets are owned, bounded waits

The official Antigravity CLI can fail with an individual subscription quota and an explicit reset duration. Previously this stopped the entire job and lost the actionable reset time. Managed processing now waits without new dispatch, retains its owner/cancellation and continues after that provider deadline plus30seconds. It neither changes model/account nor bypasses the limit.

Only a complete h/m/s duration up to24hours, anchored to the recorded official attempt finish, authorizes a wait. Legacy failure records are enriched from their saved official ERROR envelope and cli-run timestamp, without accepting any ERROR output. Unknown quota, authentication, invalid timing and exhausted retry limits still pause with concrete diagnostics.

The exchange persists quota-cooldown.json. The runner drains active siblings and blocks new dispatch. The worker preflights a known cooldown before rebuilding the pipeline, or waits in-place when it occurs during a native request; quota time does not consume the600second response deadline. provider_wait retains the actual stage/counter and Studio displays the local resume date. Read APIs never schedule or retry.

Only after expiry, the worker writes a bounded quota-retry.json ticket before archiving failure.json to quota-history. The coordinator then re-arms that packet once. At most two such retries per packet are allowed. Immutable native requests, image assignments, accepted/published replies and every CLI attempt remain untouched. Explicit manual/external exchange retains its policy.

Tests cover exact historical deadlines, invalid input, cancellation, retry caps, accepted replies, stage counters and response budgets. A real Windows coordinator with a test provider waits31seconds then retries the same packet exactly once; the native packet wrapper records reset metadata on exit3 without importing ERROR. Full real-provider completion remains an external observation after its reset.
