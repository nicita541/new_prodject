"""Guard production chunk/renderer compatibility against the 18-vs-12 regression."""
from pathlib import Path
import pytest

from app.bounded_storyboard import MAX_INFERENCE_FRAMES, POLICY, _requested
from app.scene_analysis import bounded_chunks
from app.vision import inference_samples


def test_chunk_planner_and_actual_frame_renderer_have_same_default_limit():
    assert MAX_INFERENCE_FRAMES == POLICY["max_frames"] == 18
    # Real source timestamps are preserved, not interpolated or relabelled.
    source_times = [i * .4 for i in range(MAX_INFERENCE_FRAMES)]
    assert _requested(0, 8, source_times, context=False) == source_times
    with pytest.raises(ValueError, match="frame limit"):
        _requested(0, 8, [i * .1 for i in range(19)], context=False)
    assert _requested(0, 1, [0, .95], context=True) == [0, .95]
    with pytest.raises(ValueError, match="frame limit"):
        _requested(0, 1, [0, .4, .9], context=True)


def test_default_chunk_generation_never_exceeds_renderer_policy():
    scene = {"id": "scene", "start": 0, "end": 12}
    transcript = {"segments": [], "words": []}
    chunks = bounded_chunks(scene, transcript, [])
    assert chunks
    for chunk in chunks:
        units = __import__("app.story_review", fromlist=["candidate_units"]).candidate_units(
            chunk["start"], chunk["end"], transcript, [], annotated=True, max_unit_seconds=4)
        for recovery in (False, True):
            requested = inference_samples(chunk["start"], chunk["end"], units, recovery=recovery)
            if "sampling_limit" in chunk and len(requested) > chunk["sampling_limit"]:
                # For source-POSITIVE but indivisible micro-chunks, the planner
                # allows downsampling, and the renderer must accept the cap.
                requested = [requested[round(i * (len(requested)-1) /
                           (chunk["sampling_limit"]-1))] for i in range(chunk["sampling_limit"])]
            assert len(requested) <= MAX_INFERENCE_FRAMES
            assert _requested(chunk["start"], chunk["end"], requested, context=False) == sorted(requested)
