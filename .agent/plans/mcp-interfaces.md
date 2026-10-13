# Goal
Implement separate stdio MCP connections for product control and development diagnostics, using the existing Studio backend and real repository data.

# Current state
Studio owns the HTTP service, library and single job/export queue. Diagnostics are persisted per job. `docs/mcp-scope.md` defines the requested tool groups; no MCP implementation exists.

# Constraints
Keep main unchanged; work in codex/dramatic-montage. Keep all files/dependencies in the workspace. No cloud/video processing during validation. No second product worker, arbitrary shell, credential reads, quality bypass, or extra GUI. Product tools never expose dev tools. Reads never create diagnostics or start inference. Bound outputs and validate identifiers, ownership and paths.

# Implementation
1. Pin official MCP SDK compatible with the installed runtime. Add a shared typed registry, stdio lifecycle, structured errors and bounded/redacted responses.
2. Add product tools over the existing loopback HTTP API, ownership checks, operation replay journal and settings concurrency protection. Keep backend atomic guards with the existing owners.
3. Add separate development entry point: bounded code/docs search, persisted diagnostics, trace/metrics and Git readers; whitelist isolated checks and local short benchmarks.
4. Add launch/configuration documentation, architecture decision and responsibility map. Verify tool isolation, protocol lifecycle, failure handling and existing product behavior.

# Validation
Focused pytest tests using isolated jobs/backend fixtures and SDK ClientSession over actual stdio; existing pytest suite and frontend test/lint/build commands. Do not claim model speed measurements without a real authorized run.

# Risks and rollback
MCP mutations affect real projects; identity, ownership, revisions and operation IDs guard targeting/replays. Interrupted ambiguous mutations are reported without automatic relaunch. Development execution is explicit and restricted. Removing MCP entry points/dependency restores pre-feature access; existing data formats remain usable in Studio.

# Progress
- [x] Inspect relevant API, ownership, diagnostics and proposed scope.
- [x] Protocol and dependency.
- [x] Product tools and atomic guards.
- [x] Development tools and isolated execution.
- [x] Integration/regression checks and documentation.

Official SDK installed without changing pre-existing dependency versions; pip check passed. Actual SDK ClientSession initializes both stdio servers and verifies separate catalogs/resources. The initial full regression suite passed (1423 tests + 630 subtests); frontend test/lint/build passed. Actual dev MCP studio_lint child completed with exit code 0. Project-local Codex config installed on F: without changing global settings. Additional MCP cases and a user-requested parallel social-frame feature are being integrated before final validation.

The expanded MCP suite passed 32 tests, including concurrent replay clients, finishing/caption revisions, asynchronous render delegation, archive/restore and real symlink rejection. A read-only request against actual Studio succeeded: ready, idle, older backend identity correctly detected. The two new UI workstreams are independent subsequent user requests; combined validation/restart follows their integration.

Final integration: Windows Git inherited the MCP stdin pipe and hung actual workspace_status calls despite direct service tests passing. Git now uses DEVNULL; actual stdio workspace_status completes, and the SDK regression exercises it. All 32 MCP tests passed after the fix. Combined pre-fix full suite passed 1434 tests +636 subtests; the changed MCP boundary was then rechecked separately. Current Studio is running and idle; already-connected old MCP processes need reconnect to adopt their new code/schema and expected backend identity.
