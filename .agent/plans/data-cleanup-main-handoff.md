# Reviewed data cleanup and main-branch handoff

## Goal
First reduce oversized local data while retaining working results and reusable analysis. Then merge the completed montage branch into main and create a new codex branch from main for subsequent work. Keep the current product usable throughout the handoff.

## Current state
Workspace: F:/new_prodject; cleanup branch: codex/montage-quality. Before cleanup, data totaled 9,579,852,928 bytes, dominated by jobs (8,215,946,262) and imports (1,284,011,576). Reviewed cleanup deleted exactly 1,760 files / 5,207,623,849 bytes. The after-scan totals 4,394,059,474 bytes including new private audit manifests/receipts: jobs 3,008,328,321, imports 1,284,011,576, preparation 46,323,030, diagnostics 54,574,055, settings 813,241 plus small catalog/lock files. All 23 job records, 10 registered sources and three active episodes remain.

Latest working E01 job 7153131e-e85c-4080-87f7-ee901e8d484e contains 14 no-label MP4/SRT pairs, reviewed plan/analysis/debug metadata and source identity. Independent full-media QA and actual browser checks passed. Latest active Marie job is 4702049b-51f0-483b-ab24-2fab81d9082e; the other active episode's latest completed job is 013efbd4-4adb-4f90-84df-a73d97b76b55. These three directories are retained in full.

JobManager enumerates job.json and reads it on each request; Library derives job history from those records and retains legacy ownership mappings. Cleanup kept all 23 job records and their status/source/episode identity. Twenty old records now have empty outputs lists and explicit exports_cleanup receipts, so old downloads are not advertised; history and analysis remain. Sources/catalog/settings and 42,763 retained files passed byte-hash validation (only the reviewed old job metadata changes were permitted).

## Constraints
- All scans, manifests, receipts, temporary files and operations remain in this workspace. No outside-drive cleanup, installation or provider/ASR calls.
- Retain all imports/registered sources, preparation caches, settings/secrets/ledger, catalog files and all reusable analysis JSON/model images across all jobs. Do not print or commit private values.
- Retain the three latest active-job directories in full, including outputs, source, plan, diagnostics and cached evidence.
- Delete only the exact reviewed individual file list under data. Reject absolute paths, links/junctions, changed paths/stats or candidates outside the fixed categories. No broad recursive deletion.
- Execute only after coordinator review/GO and graceful shutdown of the owned idle server; hold the existing data/.server.lock InstanceLock during mutation. A live server or active job blocks execution.
- Git mutation is handled separately by the coordinator after cleanup verification. Preserve unrelated tracked/untracked work; do not reset or sweep the checkout.

## Implementation
1. Inventory data sizes, active/archived episode ownership, latest completed jobs and large duplicates. Save a private sanitized inventory under data/diagnostics/data-cleanup-2026-10-05.
2. Freeze a private cleanup-manifest.json and cleanup_reviewed_media.py there. Planned reclaim: 5,207,623,849 bytes (about 4.85 GiB): old output files 3,684,471,046; previous-export media 356,988,193; duplicate QA MP4/WAV 334,412,291; regenerable old audio 823,582,522; old render work 8,169,797. Preserve model-stage images rather than risk cache invalidation.
3. Independently review the exact manifest/helper. Default dry-run validates without deleting or changing job records. Obtain the coordinator's concrete digest-bound execution GO.
4. Stop only the owned idle server. Acquire InstanceLock, revalidate catalog/job/protected bytes and deletion size/mtime, save original job records, then clear obsolete outputs lists with explicit exports_cleanup metadata. Keep existing statuses/history and do not invent provider confirmation.
5. Completed: unlinked the exact files under InstanceLock after the owned idle server stopped; validated protected bytes/catalogs/settings and absence of deletion targets; saved cleanup-receipt.json (completed) and after-summary.json under the private diagnostics folder. All three retained latest jobs remain completed with every registered output present (28/30/32 names), plan and transcript intact. Lock released. Runtime owner restarts the owned server and verifies latest source/debug/downloads plus old history without dead names.
6. Update this plan with actual cleanup totals. Coordinator commits the relevant handoff documentation, merges the verified working branch into main without losing unrelated work, then creates the requested future codex branch from main and reports exact refs.

## Validation
Inventory and dry-run must identify the same concrete candidates/retained jobs. Execute refuses a changed catalog, job set/status, protected content, manifest digest or file target. Existing server InstanceLock prevents concurrent job creation or worker use while cleanup runs. Old audio can be recreated by local FFmpeg extraction; retained transcript/segments prevent needless full ASR.

After cleanup verify deleted count/bytes, retained-file hashes, all 23 job/source ownership records, empty obsolete output lists, latest completed outputs and valid plan/debug metadata. Actual browser/API checks must use latest 7153131, not an old labelled copy. Do not rerun montage analysis solely to test cleanup. Before branch handoff confirm Git status, intended scoped commits and ancestry; verify main includes completed work and the new branch starts from main.

Post-cleanup runtime API QA passed on the restarted owned server (PID 6020, session 37862): health ready/busy false; all 23 jobs visible; latest 7153131 completed with 28 registered names/14 MP4s, 14-part plan and available debug metadata. Current MP4 and source returned HEAD 200 and a 64-byte range 206. Old 8d0/98291/Daba remain completed history records with zero advertised files and exports_cleanup receipts. Coordinator's refreshed browser showed all 14 playlist buttons and timeline entries, correct part-001 source playback, ready state with no error, and working enabled download-all control.

## Risks and rollback
Deleting old rendered media is irreversible from this workspace; no second full media backup is created because that would defeat space reclamation. Preserve source/analysis/plans to recreate an old version by local rendering if needed. Small original job records and a deletion receipt support diagnosis. Do not restore an old outputs list while its files are absent; restore metadata only alongside restored/regenerated files. Interrupted cleanup stops at the failing boundary and retains completed deletions/receipts, requiring a new reviewed continuation rather than a blind replay. Retained latest results stay available.

## Progress
- [x] Read-only inventory and job/catalog lifecycle inspected; 23 records and latest active results identified.
- [x] Concrete 5.207 GB reclaim scope selected; no deletion performed.
- [x] Private manifest/helper frozen; default dry-run passed 1,760 exact files / 5,207,623,849 bytes and all 23 job records. Manifest SHA256: 789254f76770c60e2cf800322569c76bfc24abcf562e95fb9d78131f1f7d5996.
- [x] Independent review/dry-run passed; coordinator issued exact manifest/helper digest-bound execution GO.
- [x] Owned idle server stopped; cleanup completed exactly 1,760 deletions / 5,207,623,849 bytes, 20 old export lists cleared and all 42,763 retained hashes verified; lock released.
- [x] After-scan saved: data 4,394,059,474 bytes including audit overhead; all 23 records/10 sources and all latest output files present. No provider, ASR or network calls occurred.
- [x] Owned server restarted; post-cleanup runtime API QA passed current result/plan/debug, source/output HEAD/ranges and old history with no dead filenames.
- [x] Coordinator's actual browser check passed; final main/new-branch handoff follows below.
- [x] Cleanup totals and handoff documentation committed as scoped commits.
- [x] Fast-forwarded `main` from 5354a40 to 153a90c (including verified `codex/montage-quality` work and scoped handoff docs). Created `codex/montage-next` at the same commit without checking it out; the workspace remains checked out on `main`. No remote push was performed.
