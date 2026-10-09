# 0026 — Coalesce source scenes without video presentation timestamps

Status: accepted, 2026-10-09.

Word-safe scene boundaries can leave a short interval without any decoded video frame PTS. Treating that interval as a standalone CURRENT scene or neighbor context makes bounded source extraction fail. The observed local episode had one such interval; a duration threshold would misclassify valid short frames and variable-frame-rate holds.

Before real scene analysis, probe the original source frame timeline once. Coalesce a frame-empty interval into the preceding analysis scene, or into the following scene when it is leading. Preserve contiguous source coverage, audio, word-safe outer boundaries and the original interval ID/range in `evidence.frame_empty_intervals`. Raw detector `scenes.json` remains unchanged; `diagnostics/pipeline/frame_backed_scenes.json` records the analysis mapping. A range with no source frames at all still fails.

Keep the storyboard's strict `[start, end)` PTS ownership and frame caps. Do not substitute a neighbor frame, round a timestamp into the interval, truncate the sampling request or manufacture visual evidence. Coalescing is technical preparation, not a semantic assertion. Ordinary semantic identity invalidates analysis checkpoints when this preparation changes.

Probing the complete episode needs a duration-scaled process timeout; ordinary short storyboard probes retain their 45-second default. The source probe remains cancellable. Consequences: one additional full source probe per analysis invocation, and recomputation after the code change. Retain previous attempts for comparison; rollback is reverting the isolated fix.

Verification: 95 focused tests passed, including real FFmpeg analysis with an ASR word in a frame-empty interval. The full Python suite passed all 1076 tests in 130.109 seconds. Independent decoding of the real episode found 34,050 video PTS; its 478 detector scenes become 477 analysis scenes and 949 technical children, with no frame-empty CURRENT children or two-second neighbor context windows. Actual FFmpeg extraction passed for repaired CURRENT/recovery and neighboring context views. Full export and editorial acceptance remain separate.
