# 0034 — Separate product and development MCP adapters

Status: accepted, 2026-10-13.

Studio remains the sole GUI and HTTP composition owner. Product MCP runs through `app.mcp_server` over stdio, uses the official pinned Python SDK and calls the existing loopback HTTP service. It never constructs JobManager, launches Studio or starts agy. Explicit project/episode/job IDs are checked against the library; current backend/workspace identity is required before mutations. HTTP owners keep their existing validators, busy checks, queue and caches.

Development MCP has a separate `devtools.mcp_server` entry point and registry. Product startup does not import devtools. Repository/diagnostic readers use allowlists and bounded pages/byte cursors, never instantiate Diagnostics or repair cache signatures. AST callers are syntactic evidence, not a claim of a complete dynamic call graph. Missing measurements/prompts are explicitly absent.

The MCP replay journal stores a request digest, operation state and redacted result under the workspace, protected by an OS-backed file lock. Reusing an operation ID with different arguments is rejected. Cancellation of a protocol request does not cancel an accepted product mutation. An interrupted pending mutation is uncertain and is never automatically dispatched again; inspect the real job and journal before choosing a new operation. This contains duplicate risk rather than claiming an atomic transaction between HTTP and the journal.

Episode settings use an optional HTTP If-Match digest checked inside Library's existing mutex. Older Studio clients remain compatible; MCP requires a revision. Catalog reads can request read_only=true to avoid source discovery/library migration. Domain code uses content_identity; it does not depend on MCP contracts.

Development checks use a fixed command catalog, workspace temp/cache paths and the existing WorkerProcess child-tree ownership. The child waits for the parent's start marker before executing a check. At most two checks run in one MCP session; disconnect cancels owned checks. A benchmark accepts only a real registered workspace video and a 120/180-second range. It holds JobManager's instance lock for its lifetime, requiring closed Studio and preventing a concurrent product startup. Product job duration has no test timeout.

Configuration is local stdio, without network listeners, OAuth extraction or API keys. Tool annotations describe effects; the actual boundary is the separate registry, path/identity/ownership validation and restricted execution. Raw file/model/document content is untrusted data. Physical deletion, arbitrary shell, code editing, Git mutation and quality bypass are not MCP operations.

Rollback: disconnect MCP entries and remove the new adapters/dependency. Existing Studio data/finishing revisions remain readable. If-Match and read_only are optional HTTP extensions. Preserve replay journals for uncertain operations; do not delete them to force retries.
