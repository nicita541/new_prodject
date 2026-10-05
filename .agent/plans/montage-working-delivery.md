# Usable montage delivery and review diagnostics

## Goal
Finish the current working branch so the user can launch montage, understand processing, review corrected E01 footage and save one or all MP4s into a chosen folder. Further unrelated improvements belong on a separate branch.

## Current state
Workspace: F:/new_prodject; branch: codex/montage-quality. Checkpoints: 8dcd0e0 retires monetary gates; ef90d37 adds seven processing checkpoints/two mode choices; 629b208 adds verified pure-ED authority and dense uncertain-candidate review; c75a8cec94b249089786daffac736ca837ad7653 integrates speech, pacing and diagnostics.

Final job **8d0c5783-94a4-4fb8-ae4c-b4c6ce0f3c8c is completed with 14 MP4/SRT pairs**, linked to episode 926f51e4-4c81-47a9-b85c-d556493edf45, project «перекус». It is a source-bound reviewed correction; original 98291dad-343d-434c-aa2a-9fbd439af3fd and rejected Daba correction remain intact. Only parts 1–3 were re-rendered; reused parts 4–14 match prior MP4/SRT hashes.

The final correction restores continuity at 71.120333–74.241, retains «Понимаю.» through its reviewed end 84.68 plus a 0.55-second handle (part 1 ends 85.23, before true OP at 88.005), removes verified ED/preview from 1335.042 onward, and applies 11 reviewed silent-footage removals totaling 36.193 seconds. The reaction at 262.012–263.6385, interior approach and basket pickup around 289 remain. Exact ranges/evidence are in [the QA report](../../docs/qa/fresh-export-2026-10-05.md).

The actual final-job browser shows 17 distinct warnings and 69 merged reason markers. Debug is off by default, uses retained source intervals/safe text, and labels model atmosphere rationale without making it verified story fact.

Chosen-folder saving passed user native acceptance after restarting the owned server in the interactive desktop context (PID 17776): the user selected a folder and confirmed all 14 separate MP4s saved. The first invisible-chooser/409 failure is recorded in the QA report. The user then requested removal of the baked-in part-number overlay; a new render-only copy of the same reviewed plan is pending.

## Constraints
- Keep tools, temporary files, media, caches and dependencies inside the workspace. Do not commit media, secrets, raw provider payloads or private job state.
- Monetary accounting remains retired. Runtime has one send plus two retries; preserve cancellation, auth/TLS checks and strict IDs.
- Preserve important quiet causal action, jokes and reactions. Motion/silence or tentative atmosphere alone does not establish story value.
- Use cached evidence/targeted review rather than whole-episode ASR or repeated initial analysis for an already reviewed correction.
- Preserve old exports/manual provenance; a reviewed correction is not a new full remote analysis.
- Public diagnostics expose bounded timings/reasons, not paths/prompts/credentials/responses. Render model text as text.
- Single/all saves use a visible native Windows chooser, registered completed MP4s and separate files. No client destination path or ZIP.

## Implementation
1. montage_recovery completed bounded speech tails, strict OP/ED proofs and final-copy assembly.
2. processing_checkpoints completed targeted empty-footage review and pacing/story/editorial regressions.
3. processing_checkpoints_review supplied actual-cut warning/reason helpers; montage_recovery integrated the off-default static timeline and UI regressions.
4. Final copy was published after rendering/copying succeeded, with recomputed selected ranges/provenance; old outputs stayed unchanged.
5. processing_checkpoints owns native-save backend; montage_recovery owns static buttons/status/tests. Single/all use POST /api/jobs/{id}/save-videos. The server validates registered sources before the chooser, streams temporary copies and suffixes collisions. UI reports cancellation, complete/incomplete receipts and partial failures. Interactive-server visibility was corrected and the user confirmed the bulk save.
6. Coordinator owns combined gates, owned-server lifecycle/Git checkpoint and actual browser route. Complete the new no-label copy and its media/browser checks, then keep unrelated work on another branch.

## Validation
The latest combined gate, including the no-label renderer change, passed **368 Python tests in 18.274 seconds and 20 direct Node UI tests**. Regressions cover speech tails, strict production bounds, weak atmosphere versus verified reactions, stale diagnostics, safe debug selection and save receipts/states.

Independent media QA passed all 14 probes/audio/plan-duration/SRT checks, full decoding of changed parts 1–3, unchanged MP4/SRT hashes for parts 4–14, no cached-word overlap in the 11 cuts, and preserved speech/reaction/basket/ED bounds. Actual browser checks loaded the final ID/real files and verified debug precision/off behavior.

Mocked-chooser integration copied real MP4s: 14/14 SHA matches, 334,114,177 bytes. The first actual action failed to show the chooser, but after the interactive-server restart the user confirmed selecting a folder and saving all 14 MP4s. Separate native single-file acceptance has not been reported. Technical checks do not certify whole-episode editorial acceptance.

The requested no-label renderer passed 33 focused subtitle/media tests in 13.724 seconds, including real rendered pixels proving no upper label while speech captions remain. Subtitle style identity 4 and renderer identity 5 invalidate old render caches. The private default-dry-run helper preserves all 14 part definitions/SRTs and limits the pending fresh render-only copy to two workers with no provider calls.

## Risks and rollback
Aggressive silence trimming can remove story; preserve independently evidenced quiet action/reactions. Rounded ASR ends require handles and cannot determine production transitions. Missing historical evidence must show uncertainty/unavailable rather than invented ranges. Folder save cancellation must release pending state and preserve sources; partial failure retains completed copies/reports count; Windows collision handling preserves existing files. Roll source back through Git; original jobs and reviewed copies remain available.

## Progress
- [x] Launch, seven checkpoints/two modes verified; financial gates removed.
- [x] Strict OP/pure-ED rules, dense uncertain-candidate review and speech-tail regressions integrated.
- [x] Eleven reviewed empty-footage cuts applied without cached speech or retained action loss.
- [x] Final 14-part copy completed, same-episode linked and independently media-checked.
- [x] Actual final-job debug verified: 17 warnings, 69 merged markers, precise selection/off behavior.
- [x] Single/all save implementation, automated receipt tests and real-file mocked-chooser integrity pass.
- [x] Native bulk folder selection/saving confirmed by the user after interactive-server restart.
- [x] Remove baked-in ASS Part overlay; keep speech captions/UI numbering and bump render cache identities.
- [ ] Render and technically check a fresh 14-part no-label copy; preserve already downloaded 8d0 outputs.
- [ ] Record final source/docs Git checkpoint and user editorial acceptance.
