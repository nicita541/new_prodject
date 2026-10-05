# Goal
Preserve visual causes and reactions between replies, and detect short production bumpers in every anime without episode-specific exclusions.

# Current state
The first automatic FumoDub run omitted the rope appearing around 222s: selected units were trimmed to spoken-word margins. Dense dialogue condensation received no images. Title screening ignored silent runs shorter than eight seconds. Baseline outputs and QA are retained.

# Constraints
No hardcoded episode names or time exclusions. Keep the existing $0.10 per-attempt limit, ledger and paid-response safeguards. Preserve existing exports. All artifacts stay in this workspace.

# Implementation
1. Preserve complete selected source units; require current visual evidence for condensation.
2. Increase storyboard coverage from eight to seventeen frames (user requested one additional frame after the initial sixteen-frame change), covering source units before supplementary shots; invalidate visual decisions, preserving factual ASR/shot caches.
3. Screen short silent units for visible production branding, with independent per-unit confirmation and conservative fallback.
4. Verify regression cases and both real source plans, then render the new attempt for user review.

# Validation
Unit tests for dialogue with silent leading/trailing action, dense-scene imagery, shifted short logos, narrative/signage protection, sampling coverage and cache migration. Full Python suite. Real-source before/after coverage and output decode/audio checks.

# Risks and rollback
Complete units may retain more breathing room. Visual pacing can still remove confirmed redundant waiting. More imagery/queries may increase cost or latency; the existing spending guard remains. Revert code/version changes to roll back; baseline exports remain accessible.

# Progress
- [x] Diagnose the actual omissions against original frames.
- [x] Implement generic selection and branding rules.
- [x] Run regression tests after final sampling/bumper changes: 287 Python tests passed (18.928s); focused story/title/sampling checks passed (51 tests).
- [x] Verify real sources and preserve comparative evidence: final new-source export has 16 validated MP4/SRT, 20 audio comparisons (minimum correlation .98286, zero best lag), and all contact sheets reviewed. Baseline decision hashes unchanged; older source unit replay/title-stage diagnostic retained without modifying its exports. See new job qa/general-quality-review.md for evidence and remaining limits.

The first candidate export exposed an abstract animated lead-in before the verified logo; added a generic, independently verified adjacent-bumper continuation check. Rendering was cancelled safely before changing that rule. The user's additional-frame request changed sampling to seventeen and analysis version to 8; the final run reuses factual ASR/shot artifacts and recomputes image-based choices. A server interruption left one reserved remote request; recovery retained its $0.0040188 ceiling and blocked replay. Per-attempt accounting remains intact.
