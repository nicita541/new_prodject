# Early-scene and part-ending verification, 2026-10-05

Development branch: `codex/montage-next`. Baseline: preserved job `7153131e-e85c-4080-87f7-ee901e8d484e`. Separate artifacts: `temp/scene-endings-final/`.

## Result
Whole silent shots and a sequence review reduce the requested early office/travel/shopping region from 89.124 to 39.703 seconds. The station-to-store commute retains 6.592 seconds instead of 23.489. Neutral reviewed source ranges no longer inherit tentative atmosphere labels.

Preview 1 is 85.23 seconds and retains the completed conversation and its selected audio tail. Preview 2 is 102.3185 seconds, ending at source 375.62 after the cashier's complete farewell, before the new reflection on Yamada. No source-specific production rules or manual timing exclusions were added. Prior exports remain preserved.

## Actual checks
- 382 Python tests, 95 subtests; 20 UI checks; diff whitespace check passed.
- Both preview MP4s fully decoded with FFmpeg; format/duration validation passed.
- Chronological exported frames every five seconds and exact original checkout-end frames inspected.
- Six audio excerpts compared with the corresponding source positions, including both endings: correlations 0.99864–0.99993; best lag 0 to -0.5ms.
- Final export repeated from cached reviews with provider cache-only mode; no new provider queries.

Measurements and contact sheets are in `temp/scene-endings-final/qa/`. Other experiment previews remain diagnostic history.

## Limits
The whole source plan was recomputed, but only previews 1 and 2 were rendered and checked. Other endings can carry fallback warnings and one late neighborhood remained uncertain. ASR/visual summaries can miss silent payoffs; these checks do not establish whole-episode or three-source editorial acceptance. The existing app attempt still displays the preserved older result; the new sample is a separate MP4 preview.

## Subsequent whole-episode rebuild
The user clarified that part 2 was an example, requiring every output part to be rebuilt. Final normal production attempt: `e5aeb8c9-076e-425b-b54f-e847e065e0e6`, same source and episode. All 36 events pass through general pacing, sequence and ending processing; only signature-validated factual/story/review caches are reused. No previous final events, plan or exports were copied.

The complete result has 11 parts with durations 70.967, 102.190, 109.223, 117.378, 85.478, 110.916, 104.406, 77.668, 111.386, 107.410 and 87.867 seconds. Selected total: 1084.889 seconds; removed: 348.241 seconds. Part 4 now includes the complete invitation/light-a-cigarette/joke/rebuke exchange through source 607.77; part 6 includes the immediate imagined greeting through source 816.92. The first full diagnostic build exposed missed farther ending candidates, prompting bounded whole-neighborhood pages and a separately versioned two-stage fallback recovery, retaining final verification confidence >=0.9.

Actual verification: 384 Python tests/95 subtests, with one existing Starlette/httpx warning; diff whitespace check passed. All 11 MP4s fully decoded and passed format/duration checks. Source chronology and every part/cut word boundary were checked: zero partial recognized words. Subtitle cues remain inside their parts. Every part's chronological exported contact sheet and all source ending sheets were inspected. Registered first/last MP4 endpoints return HTTP 200; the studio dropdown and timeline visibly show the selected latest attempt and all 11 parts.

Audio checks cover beginnings and endings of all parts. Direct comparison against the single preparation WAV gave correlation 0.89257–0.999+ and lag within 1.6875ms; independently resampling fresh matching source/output excerpts corrected the lower scores to 0.99831–0.99978, except one offset-dependent part-9 comparison. Its 0.25-second offset comparison is 0.99977 at zero lag, whereas offsets 0.02 and 1.0 give lower fresh-seek scores; the original continuous-WAV comparison is 0.97048. These are recorded measurement limitations, not a claim that every possible seek/excerpt comparison is identical.

Evidence is under `data/jobs/e5aeb8c9-076e-425b-b54f-e847e065e0e6/qa/`: full-export-checks.json, audit.json, audio-resampling-checks.json, part-009-audio-check.json, eleven overview sheets, three ending sheets and studio-result.png. Older attempts remain preserved. One nonfinal ending (part 1, source 85.17, after the completed “Понимаю”) still has an explicit model fallback warning; its source/output frames were manually inspected. Other conservative retention/uncertain-analysis notices remain visible. This completes the requested whole-episode rebuild and file checks, without claiming universal editorial quality or three-source acceptance.
