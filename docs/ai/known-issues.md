# Known issues

Track unresolved issues only when they are real, reproducible, and useful across tasks.

For each issue record:
- symptom;
- reproduction/conditions;
- affected area;
- current understanding;
- workaround, if any;
- tracking issue/link, if one exists.

Remove entries when resolved; Git/issues retain the history.

## Quality acceptance still pending
The test episode now has a whole-frame/accent export with DeepSeek story/plan. User review exposed exact-ASR-end clipping, omitted replies in retained story scenes, and an opening tail in a mixed event. Speech handles/restoration and explicit confirmed exclusions fix these observed cases; the opening tail required manual verification of source frames. Long silent commute/office material and some closing/title material can still be retained when automatic classification is uncertain. Use the source timeline to compare kept and removed footage. Technical success does not establish editorial acceptance. See docs/quality-audit.md and .agent/plans/ready-studio.md.

## Small ASR errors remain possible
The test episode includes low-confidence isolated words and proper-name errors. Bounded gap repair fixed demonstrated timing/recognition mistakes, but no confidence threshold proves whether speech is real. Original audio remains intact. Review subtitles against the source; do not silently discard ambiguous words or invent corrections.

## Visual context remains over-retained
Separate replay e6726f9f-e118-48e7-8828-10fc5aa3ec47 keeps 1350.481 s (22:30) of 1420.222 s, versus first unattended 1197.228 s. Whole selected units restore necessary silent action but also inflate margins. Contextual pacing7 removes only 7.181 s; four invalid repetition-witness batches preserve the whole batch. Short gaps below .75 s are not reviewed, and frame-based judgments over-classify held reactions. Complete-summary/uncertainty guards correctly prevent unsupported whole-event exclusions but leave mixed redundant dialogue intact. This remains an editorial limitation, not resolved by balanced part lengths. Pacing8 now requires abstract narrative/emotional-function evidence; it is tested at the domain level but its model judgments are not yet checked by a new full export. See docs/ai/editorial-investigation-2026-10-03.md and this replay's qa/final-validation.json.

## Mixed story/uploader commentary survives conservative speech protection
The first unattended FumoDub result d2396ba0-ee65-4186-848b-eb64921a6aeb is preserved for regression comparison. Generic seventeen-frame/whole-unit/title rules in f328937d-214f-4978-9508-b075596794b1 automatically remove its complete MGS bumper (source 0–5.088 s) and retain the demonstrated capture/reaction transitions without manual exclusions. Full exports and comparison evidence are in this job's qa/general-quality-review.md.

Uploader commentary remains in part 16: source 1330.23–1381.41 retains 47.45 s versus 27.34 s in the first result. Conservative recognized-speech protection does not reliably distinguish uploader/production speech from character dialogue or narrative voiceover; fuller units increase retention. Needs a general speech-role check with independent safeguards, not an episode-specific exclusion. The older anime's standalone mixed-window title diagnostic authorized no removals and does not prove automatic opening removal; its historical manually verified exclusion remains unchanged. Technical validation does not establish editorial acceptance.

## Scene threshold has limited calibration
Threshold 0.20 detects two transitions missed at 0.24 in six checked source windows. Ordinary motion reached 0.199887 in the same experiment; broad precision/recall is unmeasured. Periodic focus samples mitigate held crops but do not establish universal shot accuracy.

## API accounting is an estimate at verified prices
DeepSeek balance is a last-checked snapshot; other clients can spend the account. The displayed accumulated cost uses peak input/output rates without discounts. Unknown billing after cancellation/network failure retains the reservation and blocks further paid calls. Choosing local remains available. There is no extra total spending ceiling by default, per the user's instruction.

The user removed the USD 0.10 attempt cap. Provider balance observations now refresh independently and show account scope/staleness; the documented API does not provide per-key invoice usage. Increased funds invalidate observed-decrease attribution. Explicit uncertain-billing recovery keeps its reserved cost and blocks replay.

## Original MKV playback depends on browser codecs
The timeline streams the original file without transcoding it. A browser may reject an MKV or an unsupported source codec even though FFmpeg can export it. Ready Shorts use MP4/H.264/AAC. Original-source comparison in that case requires a compatible local player; the source remains available in the project.
