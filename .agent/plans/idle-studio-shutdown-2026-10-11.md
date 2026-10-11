# Goal
Provide one understandable stop launcher for this workspace's idle KADR server without killing unrelated Python/model processes or interrupting active work.

# Current state
`start.bat` opens/reuses a server using `/api/studio/identity`; the only shutdown mechanism is Ctrl+C in its original console. `JobManager` owns the worker tree, finishing renders, and an OS instance lock. FastAPI lifespan owns manager cleanup; Uvicorn currently uses the `uvicorn.run` convenience API.

# Constraints
Use the existing loopback/origin protections. Validate exact workspace/backend/UI identity. Refuse active analysis and finishing tasks. Keep instance lock until lifespan cleanup. All logs/cache/temp stay under F:/new_prodject. Preserve Ctrl+C, current routes and stored job formats.

# Implementation
1. Add a transient shutdown flag under manager.mutex, with analysis and finishing admission guards.
2. Add strict identity-checked POST /api/studio/shutdown. Request Uvicorn exit only while idle; roll back the flag if callback fails.
3. Add launcher --stop and a BAT wrapper. Poll readiness until this server is gone; never send OS kill commands.
4. Document BAT entry points, logging paths, limitations, and an ADR.

# Validation
Run focused pytest launcher/logging/shutdown/manager/finishing/API tests. Cover wrong identity, missing callback, active job/export, hostile origin, callback failure, task admission after shutdown, lock release during lifespan exit. Real server start/stop must be coordinated by root.

# Risks and rollback
HTTP requests admitted just before shutdown may finish before Uvicorn exits; analysis/export admission is guarded again under manager.mutex. Remove endpoint, CLI option, shutdown flag and BAT together to roll back; no data migration is needed. Idle-only refusal is intentional: cancel active processing through its existing job cancel operation first.

# Progress
- [x] Existing launcher and manager boundaries inspected.
- [x] Shutdown guards, endpoint and CLI implemented.
- [x] Focused regression checks passed: 148 passed, 26 subtests, one existing Starlette deprecation warning (7.73s). Sandbox tmp_path ACL limitation bypassed by the approved local test execution.
- [x] Operations guide and ADR completed. Real server checks delegated to the coordinator; no unowned process was started/stopped here.
