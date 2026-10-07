# Scene recovery and independent visual verification

## Decision

`scene_understanding` validates three confidence dimensions and source unit IDs. Acceptance requires every dimension at least 0.85 and no declared uncertainty. Values from 0.60 require review; lower or absent confidence requires recovery. These are model self-assessments, not calibrated probabilities.

Uncertain local analysis triggers a fresh query with denser current frames, nearby context, actual ASR and the original hypothesis. Neighbor evidence remains context-only. Failed or unresolved quality recovery retains actual speech, declared actions and brief before/after state evidence. It does not automatically retain the entire semantic scene. Cancellation, authentication, TLS, remote-service and budget control failures propagate rather than masquerading as quality fallback.

`global_verification` independently examines original current images and bounded neighbor evidence before the text global review. Trusted confirmation can clear semantic uncertainty while retaining the original summary. Trusted corrections update the final summary and add evidenced current action units. Confirmed credits and nonstory source exclusions cannot be restored by a narrative hypothesis. Every page/chunk decision remains in local/recovery/global/final provenance; partial verification stays unresolved.

## Compatibility and rollback

Analysis version 10 and derived story signatures invalidate previous understanding while factual ASR and media checkpoints remain reusable. Global verification caches include actual submitted prompt text, images, source units and provider identity. Existing event fields remain readable; confidence, state and provenance fields are additive. Reverting the stage restores the earlier semantic policy without modifying source media.

## Validation and limits

Synthetic tests cover successful correction, unresolved long scenes, short actions during speech, unknown source IDs, missing/invalid confidence, exclusion authority, confident confirmation, partially verified chunks, request page limits, damaged caches and control failure propagation. No real episode inference was performed for this stage; action interpretation quality depends on the selected model.
