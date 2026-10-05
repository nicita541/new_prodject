# Independent editorial investigation

The user explicitly requested GPT-6 Astra and GPT-6.1 Sol investigations. Both read code, saved choices and existing images; neither modified files, sent external model requests or changed jobs. Main agent integrates and verifies fixes.

## Evidence
Baseline d2396ba0 retains 1197.228 s; whole-unit f328937d retains 1369.972 s; first balanced 04d4bf38 retains 1330.520 s. Comparing baseline to the latter adds 148.290 s and removes 14.998 s. Added footage is outside identical ASR words/segments with .18 s lead/.55 s tail protection. The issue is predominantly visual margins, not extra dialogue. Older source's saved whole-unit replay also grows 1061.8415 to 1247.911 s; its historical manual opening annotation is not proof of unattended title detection.

ASR-end buckets are not semantic cause/action/reaction units. A reaction after the actual segment end belongs to the next bucket. Local window selection lacks earlier retained facts; global review receives event descriptions rather than individual transcript-backed units. Mixed unique/redundant exchanges survive these contracts. Lowering .85 deletion confidence would conceal missing evidence.

Global first-300-character descriptions omitted the job offer/debt consequences in event0017 and completion of a relationship change in event0013. This led to low-confidence suggestions to remove important scenes. Current global input keeps complete descriptions when possible; bounded excerpts include head/tail and explicit completeness, and cannot authorize whole-event removal.

Pacing3 removed 5.088–9.34 and 698.97–701.75 as production credits. Existing images show neutral academy establishment and a symbolic debt reaction with a watermark. No independent title evidence authorized these cuts. Title removal belongs exclusively to dedicated classifiers; scenery and reaction need separate editorial roles.

## Integrated safeguards and bounded improvement
- Refined uncertainty/fallback prevents global deletion; validated intentional omissions do not restore all speech automatically.
- Global omissions require reason/evidence, >=.85 confidence and complete summaries; dependencies and verified question/prefix context rescue needed prerequisites.
- Balance around actual feasible part count, then repack rather than leave a short tail; distant shots do not defeat the target.
- Pacing7 reviews speech-free margins >=.75 s in <=2 s units. Each has three current views, immutable source context before/after, exact neighboring replies and retained/discarded flags. Independent sheets use local letter IDs to prevent row/global-number confusion. A retained-witness field is required by the domain validator only for actual repetition removals, not irrelevant kept-action records. Previously validated remote answers under the stricter version6 shape can be reused after domain validation; fallback answers are not migrated.
- Neutral scenery/empty transitions can be omitted only with concrete evidence and no story change. Physical cause/action/completion, reveal and meaningful reaction remain even without speech.
- Only actual retained speech/context or an earlier kept supplied unit may prove repetition. Deleted neighbors and mutually deleted copies cannot authorize another deletion. Speech handles are immutable.
- Pacing cannot delete purported production credits; separate branding/title/closing evidence owns this decision.
- The user's examples are abstract, not object/scene rules. Pacing8 asks what specific narrative or emotional understanding deletion would lose, grounded in before/current/after views and neighboring events. Silence or an unchanged pose can carry a consequence or emotional payoff; movement alone does not prove importance. This prompt change invalidates pacing7 choices; previous-choice migration is not applied across the changed prompt. The regression protects a story-changing silent reaction even when labeled waiting. Actual export e6726f9f predates this final prompt clarification (pacing7); pacing8 has not yet been reexported.

## Remaining limits
Sparse images cannot guarantee motion/event understanding. Fine dialogue condensation needs transcript-backed beat/unit facts and references to retained replacement facts, including cross-window context. Mixed creator commentary versus narrative voiceover still needs a general role check; do not hardcode source times. Technical checks and one source replay do not establish editorial acceptance or generalization to unseen anime.

Validation and actual final export measurements are recorded in docs/quality-audit.md and the replay's qa report.
