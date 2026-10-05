# Fresh E01 export review — 2026-10-05

Final reviewed copy **8d0c5783-94a4-4fb8-ae4c-b4c6ce0f3c8c is completed with 14 MP4/SRT pairs** for episode 926f51e4-4c81-47a9-b85c-d556493edf45, project «перекус». Source: E01 - ТО Дубляжная - master.mp4, 1433.13 seconds, 1920×1080. Original job 98291dad-343d-434c-aa2a-9fbd439af3fd and first reviewed copy daba310b-e2df-4702-8600-bbb9a0acf12a remain intact. This is an explicitly reviewed correction, not a fresh whole-episode remote analysis.

## Continuity and speech in part 1

The original cut omitted 71.120333–74.241 inside an ongoing outdoor exchange. Source frames show the same pair; the reverse angle begins at 74.241. No recognized speech overlaps the gap, but the silent beat belongs to the continuous action. The final copy restores it. See [first-cut frames](fresh-export-first-cut.jpg).

The first correction ended at 84.62, clipping «Понимаю.». Local isolated Whisper review located the word at 83.680–84.680, while cached ASR ended it at 84.620. Actual story imagery continues until the OP shot transition at 88.005. Final part 1 retains source through **85.23**, adding a 0.55-second handle after the reviewed word end without restoring OP. Rounded ASR endpoints are not production boundaries.

## Ending boundary

Event 0033 (1321.64–1361.64) mixes store dialogue/night walking with ED. The new sky shot starts at **1335.042**, after walking at 1335.000; dub credits appear by 1336 and cast credits by 1337. Later footage contains ED imagery, production-committee credits around 1425, the next-episode card around 1427–1430, then black. No current-episode post-ED story was verified. Final selected source ends at **1335.042**. See [ending samples](fresh-export-ed-samples.jpg) and [transition/tail samples](fresh-export-ending-edges.jpg).

The original candidate was incorrectly typed opening at confidence 0.72, below the dense-review threshold of 0.85. Events 0033–0035 remained story with tentative atmosphere protection. Generic production review now admits uncertain candidates for independent checking while retaining strict final evidence requirements. Fully verified pure ED takes priority over interior atmosphere/reaction labels; mixed story outside verified bounds remains protected.

## Reviewed empty footage

The final copy removes these 11 speech-free source ranges (36.193 seconds total):

| Start | End |
| ---: | ---: |
| 183.058 | 186.561 |
| 188.376 | 190.190 |
| 216.8666 | 221.972 |
| 225.142 | 226.727 |
| 246.747 | 254.6295 |
| 259.342667 | 262.012 |
| 263.6385 | 265.265 |
| 271.6714 | 274.638667 |
| 276.004333 | 277.37 |
| 278.528 | 283.533 |
| 284.867667 | 287.537 |

The 262.012–263.6385 beat remains. Interior approach at 283.533–284.867667 remains; actual basket pickup around 289 is retained from 287.537 onward. Additional proposed cuts at 254.6295–259.342667 and 266.8666–268.4682 were not applied.

## Completed technical and browser checks

Independent final media QA verified all 14 files have H.264 1080×1920 video and audio, planned durations and valid SRT bounds. Changed parts 1–3 passed full decode with exit code 0. MP4 and SRT hashes for parts 4–14 match the prior Daba copy. All 11 removals contain zero cached speech words and do not intersect selected output. Evidence is in the final job's private qa/independent-media-qa.json.

The export source checkpoint is c75a8cec94b249089786daffac736ca837ad7653. The latest combined gate, including the no-label renderer change, passed **368 Python tests in 18.274 seconds and 20 direct Node UI tests**. The actual built-in browser loaded the exact final job and real MP4s, displayed **17 distinct warnings and 69 merged reason markers**, and verified precise source selection plus debug-off behavior. Отладка анализа is off by default; atmosphere annotations are model rationales, not independently verified story facts. Warning/reason filtering uses retained intervals and explicit unit bounds, not guessed list pairings.

## Chosen-folder saving: user-confirmed native success

Скачать MP4 and Скачать все видео are intended to use the same local Windows folder-picker flow. POST /api/jobs/{id}/save-videos accepts a selected registered filename or all:true; the client supplies no destination path. Files are saved separately without ZIP. Name collisions receive a numbered suffix, cancellation is reported, and partial-copy errors include the saved count. Both buttons are disabled while an action is pending; source playback/SRT download remain separate.

Automated integration selected a workspace folder through a **mocked chooser** and copied all 14 real MP4s: all SHA hashes matched, total **334,114,177 bytes**. Read-only peer review found no blocking issue in registered-file containment, local request protection, Windows collision handling or partial receipts.

The first native attempt failed: no chooser was visible, and a later action returned 409. After restarting the owned server in the interactive desktop context (PID 17776), **the user confirmed choosing a folder and saving all 14 videos**, with a screenshot showing the separate MP4 files in Documents. This is actual user acceptance of the bulk native flow, distinct from the mocked-chooser integrity test. A separate actual single-file native save has not been reported. Whole-episode editorial acceptance remains separate.

## Part-number overlay removal: new render-only copy pending

The user identified the baked-in top label Часть 1 as unnecessary. The renderer now removes the ASS Part style/dialogue while preserving speech captions and playlist numbering. Subtitle style identity increases to 4 and renderer identity to 5 so future resume cannot silently reuse labelled exports. Focused subtitle/media checks passed 33 tests in 13.724 seconds, including a real FFmpeg frame with no upper label and visible speech captions.

A default-dry-run local helper validates the completed 8d0 copy and preserves every part/cut/focus/subtitle field. It will re-render all 14 parts with at most two workers into a new job, retaining the already downloaded 8d0 output unchanged and publishing only after successful completion. No new story analysis or provider calls are needed. The new no-label copy has not been rendered or media-accepted yet.
