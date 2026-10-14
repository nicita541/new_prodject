# 0039 — Processing modes and cache lineage

Date: 2026-10-13

## Problem
Every episode launch created an empty job, although retry could reuse its checkpoints. Aggregate analysis signatures included downstream planner code. Development needs selective recomputation and plan inspection without inference or encoding.

## Decision
Studio offers `full`, `incremental` and `plan_only`, defaulting its draft to incremental. Existing API requests without a mode retain full behavior. Both job creation endpoints accept `processing_mode` and optional `reuse_job_id`; episode launch may still omit its body.

`processing` owns validation, an explicit checkpoint allowlist, independent copies and final analysis snapshot provenance. `jobs` selects the latest stopped source/episode-owned candidate whose source SHA-256 matches actual bytes; explicit foreign lineage is rejected. Legacy jobs resolve through library ownership. Cancellation, job state, provider attempts, manual packets, finishing state, diagnostics and credentials do not transfer. Sources and previous jobs remain unchanged. Copies can require significant disk space, especially clean parts and MP4s.

Full starts without inherited checkpoints and isolates DeepSeek responses by job; retries of that job can resume. Incremental inherits artifacts and uses existing stage validators. Its response-cache lineage can read ancestor full-run successes and ordinary shared-cache answers. Export validation checks actual MP4/SRT, with copy2 preserving modification times.

Semantic signatures are scoped to perception, story, late analysis and planning. Actual planner consumers in pacing/endings remain late-analysis dependencies: planner changes can repeat those checks while retaining ASR, scene understanding and story checkpoints. Preparation records extraction/tool, ASR model and inference-code identities. Legacy preparation checkpoints adopt a manifest baseline on first reuse. Appearance, rendering code and music have separate export dependencies.

Plan-only validates `analysis-final.json` against source bytes, snapshot digest, provider, layout, editorial profile, supplied-transcript settings and transcript checkpoint, then builds a fresh plan with current planning preferences. Legacy snapshots require source/provider validation and matching inherited job settings. This explicit mode freezes upstream analysis despite code/model changes. The current quality gate remains mandatory; failure requests incremental processing without model recovery. It skips briefs and all encoding, returning no output files. Upstream checkpoints remain available to subsequent incremental runs. UI shows cached analysis and unnecessary export, provides source-timeline inspection and disables absent-video/download controls.

## Compatibility and rollback
No previous job is migrated or deleted. Manifests and fields are additive; old public jobs default to full. Removing mode controls and new launch arguments restores fresh launches. The first deployment can conservatively miss old aggregate signatures; subsequent scoped identities and stage validators govern reuse.

## Verification
Fake-worker/API/pipeline tests cover defaults, ownership, source replacement, independent copies, corrupt snapshots, plan-only without installed models, progress, lineage and forbidden inference/encoding. Stub DeepSeek tests cover full namespace isolation and inherited reuse. Studio DOM smoke covers mode explanations and source-only plan review. These tests do not assert real-media inference or encoding quality.
