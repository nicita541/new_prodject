# Goal

Implement all four FIX STAGE milestones from the 2026-10-07 user attachment. Production accepts raw video and automatically obtained audio/ASR/evidence. It must derive boundaries, states/actions, selections, relations/arcs and continuity internally. Raw-video E2E quality tests must never inject correct semantic answers; structural unit tests remain distinct.

# Current state

Branch `codex/dramatic-montage`, starting HEAD `05de12e75f966736a57b7ba00106349cd9caad77`, clean worktree. Prior four stages preserved. Last full checks: 622 Python tests and 23 UI tests. Production scene features are RGB/spatial descriptors; audio and named state inputs mainly exist in pure-function tests. Later story refinement still has uncertainty keep-all branches. Profiles lack measured temporal motion, arcs primarily consume preexisting facts, unknown continuity warns without targeted investigation. Portable FFmpeg, Python and both local Qwen models/projectors are present. Several imported real episodes are available for calibration; keys remain untouched.

# Constraints

All generated media, model processes, caches, diagnostics and temporary files stay inside `F:/new_prodject`. No main edits, no rollback of previous stages, no automatic downloads or paid calls. One local model session at a time for 8GB VRAM. Preserve source/word timestamps, confirmed source exclusions, cancellation/auth/TLS/budget control errors and additive APIs. A synthetic video or fake adapter mechanism test cannot be reported as real semantic quality proof.

# Implementation

1. Production perception: source-only perceptual descriptors, intra-shot motion, audio and fade evidence, sub-threshold proposals; cheap three-way boundary classification followed by targeted VLM only for ambiguous boundaries. Frame evidence, strict schemas, cached decisions and production sanitization; label-free raw-video fixtures and actual local-model stage-1 quality runs.
2. Unified understanding/selection confidence and local → dense recovery → disputed-question adjudication; remove uncertainty/error keep-all and generic atmosphere protection, preserve evidence-specific reactions/actions/causal dialogue, high-confidence unit-based global replacement and final unresolved analysis gate.
3. Separate measured physical motion from editing density, continuous scores and real-clip calibration; one finalized episode profile consumed by planner. Repair mandatory bridges before allocating ranked optional budget; explain mandatory overflow.
4. Automatic relations/roles/arcs and canonical state facts; punctuation-independent dialogue relations; targeted continuity verification of omitted current units with no unverified endpoint bridges. Iterative automatic final quality gate before render. Run full label-free raw-video E2E A–J with actual model responses, then report every requirement and commit separately.

# Validation

At each milestone run `tools/python/python.exe -m unittest discover -s tests -q`, `tools/node/node.exe --test --test-isolation=none tests/test_ui.cjs`, `git diff --check`, focused regressions and relevant real-video flows. Use inherited-ACL UUID directories under workspace temp. Keep fast structural/mechanism tests distinct from explicitly invoked production-model quality E2E. Persist input hashes, model/prompt identities, actual responses, source frames and assertions. Fail or report unresolved quality; never count a skipped or fake-adapter E2E as passed.

# Risks and rollback

Similar views and subtle physical actions can defeat cheap descriptors; targeted visual verification remains uncertain evidence and final gates must expose failure. Sequential inference and short cached fixtures bound runtime/VRAM. Real-model tests can reveal unsupported behavior and must drive fixes without weakening assertions or feeding answers back. Revert an individual FIX STAGE commit to restore its prior policy; factual source/ASR remain reusable, changed signatures invalidate derived artifacts.

# Progress

- [x] Read new requirements, verify branch/HEAD/worktree and relevant runtime/code.
- [x] FIX STAGE 1 implementation and real-model quality: seven raw-video fixtures passed, 25 actual LocalVision requests (reverse shots needed none). Final snapshot: 650 Python tests passed in 71.379s, 23 UI tests passed, focused 28 regressions passed, diff check passed. Saved as the separate stage-1 commit; its SHA and file list are recorded in the stage report.
- [ ] FIX STAGE 2: uncertainty/selection adjudication, full checks and commit.
- [ ] FIX STAGE 3: motion/profile/calibrated budget, full checks and commit.
- [ ] FIX STAGE 4: automatic structure/continuity/gate, full raw-video E2E, full checks and commit.

Scoped parallel work follows `.agents/skills/multi-agent-execution`: detector agent owns only new cheap-evidence module/tests; fixture agent owns only new raw-video fixture/runner files. Coordinator owns boundary integration, all later stages, VRAM sessions, reviews, combined checks and completion claims.

Stage 1 evidence: `scratch/raw_video_quality/runs/20261007T110627531114Z/quality_summary.json` and exact requests/responses/frame hashes. Initial room test exposed ambiguous opposite-wall ground truth; retained it as an optional challenge and made the required similar-room fixture distinguishable by actual architecture in the same palette. An uncertain boundary now receives one original-frame-pair adjudication; no threshold was reduced. A Windows console encoding failure was fixed with compact ASCII-safe output and checkpoint-resuming append-only recording. 28 new fast regression tests (13 perception, 11 boundary, 4 input contract), separate from seven production-model quality scenarios. All twelve real calibration contact sheets were manually reviewed; measured clip data and review-only held-out categories remain outside pipeline inputs. Calibration thresholds and later milestones are still pending.
