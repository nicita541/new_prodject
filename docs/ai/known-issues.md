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

Scoped recovery does not yet support changing one semantic boundary or safely merging changed owner proofs into cross-owner story/dialogue relations. `quality_recovery` leaves those cases explicitly unresolved and preserves unaffected evidence instead of triggering whole-episode paid reanalysis. Implement actual owner/endpoint dependency merging before restoring automatic recovery. See [ADR-0050](decisions/0050-needed-data-for-all-model-checks.md).

Official agy1.3.3 stream-json supports only text blocks. Long text-only global review now uses verified UTF-8 stdin; image packets must retain tested CLI @ attachments and Windows argument-size splitting. A long-stdin image-only nonce test did not read the attached frame; an explicit image block was rejected before inference with0tokens. The packet script refuses overlong image input before paid launch. Do not raise image batch limits on the assumption that stream-json carries images. See ADR0030 and docs/antigravity-manual.md.
Genuine fresh120/180s local benchmarks both timed out around3600s at story condensation without a render. The user requires roughly30min for180s; these attempts fail that target. ASR takes about27–29s, while sequential9B requests and technical chunk fanout dominate. Future benchmark default is1800s; no quality gate was weakened. See docs/audit/performance-results.md and findings.md. A successful single Gemini packet is not full-series quality or speed acceptance.
The test episode now has a whole-frame/accent export with DeepSeek story/plan. User review exposed exact-ASR-end clipping, omitted replies in retained story scenes, and an opening tail in a mixed event. Speech handles/restoration and explicit confirmed exclusions fix these observed cases; the opening tail required manual verification of source frames. Long silent commute/office material and some closing/title material can still be retained when automatic classification is uncertain. Use the source timeline to compare kept and removed footage. Technical success does not establish editorial acceptance. See docs/quality-audit.md and .agent/plans/ready-studio.md.

## Small ASR errors remain possible
The test episode includes low-confidence isolated words and proper-name errors. Bounded gap repair fixed demonstrated timing/recognition mistakes, but no confidence threshold proves whether speech is real. Original audio remains intact. Review subtitles against the source; do not silently discard ambiguous words or invent corrections.

## Visual context remains over-retained
Separate replay e6726f9f-e118-48e7-8828-10fc5aa3ec47 keeps 1350.481 s (22:30) of 1420.222 s, versus first unattended 1197.228 s. Whole selected units restore necessary silent action but also inflate margins. Contextual pacing7 removes only 7.181 s; four invalid repetition-witness batches preserve the whole batch. Short gaps below .75 s are not reviewed, and frame-based judgments over-classify held reactions. Complete-summary/uncertainty guards correctly prevent unsupported whole-event exclusions but leave mixed redundant dialogue intact. This remains an editorial limitation, not resolved by balanced part lengths. Pacing8 now requires abstract narrative/emotional-function evidence; it is tested at the domain level but its model judgments are not yet checked by a new full export. See docs/ai/editorial-investigation-2026-10-03.md and this replay's qa/final-validation.json.

## Mixed story/uploader commentary survives conservative speech protection
Resolved in ADR-0018 via general `_is_dub_or_title_narration` filter: fandub studio announcements, translator credits, and episode title recitation are no longer protected as character dialogue in `_protected_speech`, allowing sequence cleaners and story condensation to remove them without episode-specific exclusions. The first unattended FumoDub result d2396ba0-ee65-4186-848b-eb64921a6aeb is preserved for regression comparison. Technical validation does not establish editorial acceptance.

## Scene threshold has limited calibration
Threshold 0.20 detects two transitions missed at 0.24 in six checked source windows. Ordinary motion reached 0.199887 in the same experiment; broad precision/recall is unmeasured. Periodic focus samples mitigate held crops but do not establish universal shot accuracy.

## Historical API accounting is retired
Runtime no longer maintains balance observations or money ledgers and does not impose an attempt spending ceiling. Historical accounting files remain on disk for reference. Actual provider charges must be checked in the DeepSeek account; successful-response caching avoids repeating completed requests.

## Original MKV playback depends on browser codecs
The timeline streams the original file without transcoding it. A browser may reject an MKV or an unsupported source codec even though FFmpeg can export it. Ready Shorts use MP4/H.264/AAC. Original-source comparison in that case requires a compatible local player; the source remains available in the project.
