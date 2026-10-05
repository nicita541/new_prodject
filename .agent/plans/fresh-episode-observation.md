# Goal
Run the newly supplied episode «Забота об одарённой девушке», episode 1 (FumoDub), through the normal product flow and preserve its automatic result to discover defects on unseen footage.

# Current state
New root MP4 registered as source 18d4cfdc-497b-4aa0-b9f2-6472fda923ae (265346538 bytes). Previous anime has its separate project/episode and 13 completed Shorts. The server is idle and ready.

# Constraints
User requests minimal intervention: no manual scene/opening/dialogue changes, no tuning based on this episode before its first result. Use defaults DeepSeek-plan/cinema/accent and the authorized USD 0.10 per-attempt cap. Preserve originals, checkpoints, costs and the first result. No automatic paid retries or extra paid diagnostics. All artifacts inside the workspace.

# Implementation
1. Create a separate anime project and episode 1 using the UI, select the new source and launch once.
2. Observe job status/logs without mutating decisions or cancelling a healthy run.
3. After completion/failure, preserve evidence and inspect output metadata, decode errors, chronology, captions, opening/ending and dialogue boundaries. Reuse existing local QA scripts; no fixes during this observation run.
4. Report concrete defects with source/output times and distinguish measured findings from review uncertainties.

# Validation
Normal browser flow, saved provider/layout/captions, one attempt and spend ceiling. Final outputs or exact failure stage, local decode/contact sheets/audio comparisons where available. Findings linked to original evidence.

# Risks and rollback
ASR/story may miss dialogue or misclassify titles. A failed first attempt is a useful observation; record rather than silently retry. Project/episode can be archived recoverably; do not delete its checkpoints or outputs.

# Progress
- [x] New project/episode and normal launch
- [x] Automatic run observed
- [x] First result reviewed and findings recorded

## Launch evidence
Created project 66dc5cc5-4d01-4dcb-9ef9-432a4e9a7648 and episode fded68de-ab03-4376-b486-d1334b3ca636 through the browser; selected the new registered video and clicked «Запустить монтаж». First job d2396ba0-ee65-4186-848b-eb64921a6aeb is running with deepseek_plan/cinema/accent. Source probe: 1420.221979 s, 1920×1080 H.264, AAC. A read-only job observer writes runtime evidence under this job's qa folder; review-origin.json records fresh launch/no copied processing artifacts. No source or model decisions changed.

## Result
Completed without retry/manual intervention. 14 MP4/SRT, 1197.228 seconds (84.3% of source); $0.056466 estimated spend under $0.10 allowance. Observer recorded completion at 851.2 s after it started. Decision artifact hashes unchanged from first rendering to completion. All 14 outputs decoded; all contact sheets viewed, 41 source/output audio samples correlate >=0.97504 with best lag 0 ms. Plan has no partial recognized words, nonchronological/duplicate cuts or out-of-part cues. These checks do not certify every spoken boundary or ASR accuracy.

Two uncorrected automatic selection defects: MGS studio bumper in part 1 at 0–5.088 s; dubbing commentary/subscription appeal retained in part 14 at output 53.52–80.86 s (source 1330.23–1357.57). Both are mixed story/title event cases. Report/evidence under data/jobs/d2396ba0-ee65-4186-848b-eb64921a6aeb/qa/first-result-review.md. Actual UI automatically reached this episode's review screen with 14 parts; preserved user's playback state while saving final-ui.jpg. User will review and report further issues; no algorithm/plan/caption changes applied during this run.
