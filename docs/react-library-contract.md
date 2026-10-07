# React API contract and hotfix verification

The server and `Library.snapshot()` are the wire-contract authority. React previously assumed `project.episodes`, string job IDs and a separate `trash` object. Real responses have flat projects/episodes, object job references and `archived_at` tombstones. This caused empty episode pages, zero counts, invalid job URLs and missing trash.

`frontend/src/library/selectors.ts` centralizes ownership, active/archive filtering, completed attempts and running/queued delete locks. Projects/Episodes/Edit/Review/Trash now consume the flat snapshot. Edit prioritizes running, queued, then newest reference. Review verifies ownership and completed status before fetching a job by `ref.id`.

## Endpoint audit

| React request | Actual response / request constraints |
| --- | --- |
| GET `/api/health` | `{ready,busy,missing}` |
| GET `/api/library` | `{projects,episodes}`; episode jobs are `{id,status,created_at}` |
| POST `/api/projects` | Project; request `{title}` |
| POST `/api/projects/:id/episodes` | Stored episode without snapshot-only jobs; request `{number:number|null}` |
| DELETE project/episode; POST restore | Both `{id,archived:boolean}` |
| PUT episode settings | Requires `source_id`; layout/caption/provider have server defaults; returns stored episode |
| POST episode jobs | Public Job, HTTP 201 |
| GET `/api/sources`; POST `/api/import` | Source array / imported Source, HTTP 201; import uses multipart XHR |
| GET jobs/job; POST cancel/retry | Public Job records; status is queued/running/completed/failed/cancelled/interrupted |
| GET job plan | Source and parts; nested `part.cover_context`; `debug_timeline` and `quality_summary` belong to plan |
| Public job files | `{name,url,subtitle_url,duration}`; subtitle URL and duration can be null |
| POST job reset-budget | Accounting fields: accounting_enabled/attempt/limit_usd/charged_ceiling_usd/remaining_usd/job_total_usd |
| POST job open-folder; music open | `{opened,path}`; errors are non-2xx API errors |
| POST job save-videos | Request `{all:true}` or `{filename}`; success `{cancelled,count,files}` |
| GET/PUT music | Response includes enabled/volume/track/mode/part_tracks/tracks/fade_in/fade_out. PUT requires enabled/volume; sends only accepted setting fields. Track and per-part values can be null. `choose_track()` explicitly treats string `none` as silence; null allows random selection. |
| GET DeepSeek status | configured/budget_usd/charged_ceiling_usd/remaining_usd/model; monetary values nullable |
| POST DeepSeek check | available/model/vision_supported/balance_infos; vision_supported nullable |
| Job source and subtitle media | Registered `/api/jobs/:id/source` and `file.subtitle_url`, with `?download=1` for subtitles |

No production backend contract was changed. Legacy remains available. Invalid nested library/string-job payloads are rejected at the React library boundary. Archive/restore tests use isolated real backend state.

## Actual local application check, 2026-10-08

The running app at `http://127.0.0.1:8765` returned HTTP 200 for GET `/api/library`: **6 projects and 7 episodes**, with exactly `projects` and `episodes` as root fields. Raw responses are saved under ignored `scratch/react-library-hotfix/actual-library-before.json` and `actual-library-after.json`.

Using the actual browser, not mocks:

- Projects: 3 active projects, each showing `Серий: 1 · готовы: 1`; same records and counts in legacy.
- Episodes: existing project `31b3525c-b030-474a-bd6f-2bc869f02bce` (Забота об одарённой девушке) shows its Series 1, episode `2f496c89-47d0-4a07-8234-a3e53a86c9d8`, 3 attempts; same episode and completed review ID in legacy.
- Edit: that episode loads saved source/layout/caption/provider settings and the newest failed attempt. Historical DeepSeek failure is displayed as its existing job status; this check did not launch a new model job.
- Review: completed reference `f328937d-214f-4978-9508-b075596794b1` opens its plan, 6 registered shorts, timeline, quality notes, subtitle link and nested cover context. No `[object Object]` job URL.
- Trash: 3 archived projects plus 1 individually archived Series 1 under active project перекус. Titles, parent title and membership match legacy. Archived-project children are not duplicated.

The checks were read-only on the user's existing library. Video playback/export was not part of this contract smoke check. The browser error log returned no entries. Restore/refetch and running/queued locks are exercised by regression tests, not destructive actions on the existing catalog.

The backend-generated shared fixture contains 2 active projects, 4 active episodes, completed/running/failed/cancelled/interrupted job references, an archived project and an individually archived episode. `scripts/export_react_library_contract.py` regenerates it; `tests/test_react_library_contract.py` compares an actual fresh GET response to the committed JSON.

## Executed validation

- `npm test`: 78 tests passed in 20 files, including flat parsing, selectors, all five library screens, restore/refetch and job ownership/status.
- `npm run build`: production TypeScript/Vite build passed.
- `npm run lint`: passed with 7 React effect warnings; no lint errors.
- `tools/python/python.exe -m unittest discover -s tests -q`: 762 tests passed in 97.642 seconds, including 2 new real backend contract tests.
- `tools/python/python.exe -m pytest tests/test_server_routing.py -q`: 4 passed. TestClient now uses the real permitted loopback host, preserving production host/origin protection.
- `tools/node/node.exe --test --test-isolation=none tests/test_ui.cjs`: 24 legacy UI checks passed.
- `git diff --check`: passed.

Existing malformed component mocks and compile errors were repaired without disabling checks. Timeline diagnostics now set the same reviewed source interval as the legacy debug click, allowing an explicitly enabled playback limit to stop at its end.
