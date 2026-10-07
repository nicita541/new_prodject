# Semantic scenes and evidence diagnostics

## Decision

`app.media_probe` retains montage-shot ownership. `app.scene_detection` obtains source-frame descriptors and groups shots using visual/background continuity, recurring camera views, speech gaps and available state/audio evidence. A camera cut is not automatically a semantic scene. Descriptors do not identify characters or actions; weak evidence remains explicit uncertainty.

`app.scene_analysis` owns local understanding. A scene may have multiple technical analysis chunks, all referencing its `parent_scene_id`; chunk summaries/selections are merged into one semantic event. Previous/next scene evidence is explicitly context-only. The forty-second setting is only a technical chunk limit.

Narrative units can split inside a long spoken turn at real word edges near visual transitions. Production-sequence ownership separately retains complete acoustic replies and their tails. Storyboards preserve unit centers, short-action bursts and before/current/after transitions. Canonical scene collages remain available to existing title/story/source-role stages.

`app.pipeline_diagnostics` writes append-only timeline records plus factual shots, scenes, shown storyboard timestamps/reasons, run status, warnings and summary under `data/jobs/<id>/diagnostics/pipeline/`. Diagnostics omit credentials and never replace authoritative checkpoints. Inference failures retain their original exception and per-attempt evidence.

## Compatibility and rollback

Analysis version 9 invalidates derived semantic decisions while preserving factual media/ASR. Scene/features have separate source/transcript/settings identities. Cache observations must not enter semantic identity. Stage rollback is a Git revert; sources and ASR remain intact. Existing API events and planner fields remain readable, with additive scene/chunk/evidence metadata.

## Validation and limits

Regression coverage includes conversation→binding→car, ninety-second dialogue, reverse shots, visual handover during speech, short silent actions, contextual ownership, cache reuse and model failure. Source-frame extraction is exercised with local synthetic FFmpeg media. Local visual distances are heuristic evidence, not calibrated probabilities; accurate action understanding still requires the visual model and later recovery/global verification.
