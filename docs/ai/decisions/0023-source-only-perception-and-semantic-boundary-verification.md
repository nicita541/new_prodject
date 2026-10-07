# Source-only perception and targeted semantic boundary verification

## Decision

Production scene grouping receives factual video/audio/ASR and measured candidates. `media_evidence` decodes actual source PTS, lighting-normalized luminance/gradient perceptual and background vectors, intra-shot Farneback flow, PCM energy/spectrum, ASR overlap and fade/black evidence. The RGB descriptor remains a separate cheap color signal. Perceptual vectors and optical flow do not claim locations, named people or recognized physical actions.

Accepted montage shots remain the stable shot API. Raw FFmpeg candidates, including suppressed cuts, and independent perceptual/audio/fade/motion proposals remain available for semantic review. Secondary proposal clusters bound review demand while preserving original evidence. No FFmpeg 0.14 threshold can veto an independently measured proposal. Temporal motion excludes camera-cut pairs and exposes residual/global motion, coverage and limitations separately from raw/accepted editing frequency.

`semantic_boundary` classifies each candidate as obvious same scene, obvious source-context change or ambiguous. Only ambiguity requests a structured visual review of original high-resolution BEFORE/BOUNDARY/AFTER frames with actual PTS, measured audio/ASR evidence and no correct semantic labels. Strict flags, finite confidence, concrete evidence and consistency checks guard the response. A trusted location or physical/object-state change can create a semantic edge; a trusted same-scene decision prevents reverse-shot fragmentation. Weak or failed review remains explicit unresolved evidence for later analysis gates.

The production `analysis.analyze` path always computes source perception and supplies its selected provider to scene verification. The earlier source-descriptor-only `scene_checkpoint` mechanism remains callable without a vision provider for API/test compatibility; it is not production semantic-quality proof. Production shot ingestion strips supplied semantic fields. Pure function tests can still supply artificial facts to isolate grouping logic.

Source/policy/model/prompt/image identities protect perception and boundary checkpoints. Model output selects decisions about existing source candidates rather than generating timestamps. Measured audio is supplementary evidence and cannot alone authorize a scene split. Requests, responses, frame hashes, source timestamps, cheap triage, accepted/rejected proofs and uncertainty are preserved in job pipeline diagnostics.

## Validation and rollback

Fast tests exercise embeddings, actual flow/PCM/source-frame extraction, sub-threshold proposals, strict response schemas, cache invalidation, label sanitization and cancellation. Seven decoded synthetic video fixtures contain ordinary pixels and timed ASR only; expected facts exist solely in the evaluator after production execution. The explicit `scripts/run_raw_video_quality.py --run-stage1` command uses actual LocalVision and records exact requests/responses; fake adapters cannot qualify as semantic quality.

The new stage invalidates derived analysis with analysis version 13 and scene detector/grouping version 3 plus actual component hashes. Source and factual ASR remain reusable. Revert this FIX STAGE commit to restore the prior scene path; do not copy older semantic decisions into a new identity. Existing accepted shot IDs and word-safe source contracts remain intact.

## Limits

Image-structure descriptors are robust measurements, not semantic embeddings from a learned scene-recognition model. Their uncertainty routes to the actual vision model. Optical flow includes camera motion and cannot prove an action; inadequate measurement coverage remains explicit. Model confidence is self-assessment, not calibrated probability. Real-video calibration and automatic selection/continuity gates belong to the following FIX STAGE milestones. Passing structural or fake-adapter tests alone is never reported as completed production quality.
