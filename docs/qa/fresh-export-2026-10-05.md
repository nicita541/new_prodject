# Fresh E01 export review — 2026-10-05

Read-only review of completed job `98291dad-343d-434c-aa2a-9fbd439af3fd` (`E01 - ТО Дубляжная - master.mp4`). The job reports 15 parts and completed status. Its plan records a 1433.13-second, 1920×1080 source and 34 review warnings. This was a source/plan visual audit; I did not rerun the job, make API requests, decode all 15 exports, or change its outputs.

## Source continuity in part 1

The first output cut list is `0.0–71.120333` followed by `74.241–84.62`, dropping 3.121 seconds. Source frames at 71.120, 73.000 and 74.000 show the same two people in the ongoing outdoor exchange; the reverse camera angle begins at 74.241. The transcript has no recognized speech from 69.01 to 75.35 seconds, so the omission removes a silent visual beat rather than a separate dialogue line. The jump is inside a continuous action and is a strong candidate for restoration. See [first-cut frames](fresh-export-first-cut.jpg).

## Ending sequence in the last parts

The current plan places story events 0032–0035 at 1283.28–1433.13. Event 0032 is a convenience-store conversation through 1321.64. Event 0033 (1321.64–1361.64) combines the store scene, a night walk, and the start of the credits montage; it should not be discarded as one block. Frames show the store scene at 1328, the man walking at 1330–1335, a new sky shot beginning at source 1335.042, the first dub-credit overlay by 1336, and cast credits at 1337–1338. Credits and the ending montage continue at sampled points 1340, 1360, 1390, 1405 and 1408. This places the visual boundary at 1335.042; the contact sheet does not verify an audio boundary.

Event 0034 (1361.64–1401.64) is an ending/credits span in the sampled frames. Event 0035 (1401.64–1433.13) contains later character/product images, production committee text around 1425, a next-episode preview card around 1427–1430, and black at 1433. These samples provide no evidence of current-episode post-ED plot; do not keep the tail as story on that assumption. See [ending samples](fresh-export-ed-samples.jpg) and [transition/tail samples](fresh-export-ending-edges.jpg).

The classification path explains why the credits were retained: the ending candidate was labelled `opening` with confidence 0.72, while the dense boundary check requires at least 0.85. Events 0033–0035 were consequently left as `story` and their atmospheric ranges were protected. This is the likely cause of the ending over-retention; event 0033 still needs a mixed-boundary decision because its early portion contains actual episode action.

## Verification limits

All source frames were extracted locally with the project's FFmpeg binary. I did not perform full video decodes or validate every SRT cue, because review priority shifted to the visible continuity and ending-classification defects before those checks began. The original job and exports remain untouched.
