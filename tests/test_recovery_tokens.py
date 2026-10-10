"""Regression coverage for truthful token accounting and subframe scene salvage."""
import json
from pathlib import Path
import tempfile

from app.token_usage import record, summary
from app.scene_detection import coalesce_subframe_scenes


def test_tokens_are_real_success_and_rejected_calls_and_survive_restart():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        assert summary(root)["all_tokens"] == 0
        record(root, "local", "qwen-4b", {"usage":{"prompt_tokens":120, "completion_tokens":30, "total_tokens":150}})
        record(root, "deepseek", "deepseek-chat", {"usage":{"prompt_tokens":600, "completion_tokens":100, "total_tokens":700}})
        # No fake tokens when the provider did not return usage.
        record(root, "local", "qwen-4b", {"choices":[{"message":{"content":"{}"}}]})
        record(root, "local", "qwen-4b", {"usage":{"total_tokens":-10}})
        stats=summary(root)
        assert stats["local"]["total_tokens"]==150
        assert stats["deepseek"]["prompt_tokens"]==600
        assert stats["deepseek"]["total_tokens"]==700
        assert stats["all_tokens"]==850
        assert stats["local"]["calls"]==1
        assert stats["deepseek"]["calls"]==1
        assert "qwen-4b" in (root/"token-usage.jsonl").read_text("utf-8")
        assert "token-usage.jsonl" not in json.dumps(stats)


def test_38ms_and_80ms_subframe_scenes_join_adjacent_without_losing_any_source():
    def row(name, start, end):
        return {"id":name,"start":start,"end":end,"shot_ids":[name],
                "candidate_ids":[],"boundary_reason":["shot_cut"],
                "confidence":.99,"uncertain":False,
                "evidence":{"source_segments":[{"id":name,"start":start,"end":end}]}}
    scenes=[row("first",0,4),row("pause",4,4.038),row("talk",4.038,8),
            row("other",8,8.08),row("end",8.08,12)]
    original=json.dumps(scenes)
    cleaned=coalesce_subframe_scenes(scenes)
    assert [(item["start"],item["end"]) for item in cleaned]==[(0,4.038),(4.038,8.08),(8.08,12)]
    assert [item["id"] for item in cleaned]==["first","talk","end"]
    assert cleaned[0]["evidence"]["merged_subframe_scenes"][0]["id"]=="pause"
    assert cleaned[1]["evidence"]["merged_subframe_scenes"][0]["id"]=="other"
    assert sum(item["end"]-item["start"] for item in cleaned)==12
    assert json.dumps(scenes)==original  # no mutation of saved source evidence


def test_solo_subframe_scene_is_never_silently_dropped():
    scene={"id":"only","start":0,"end":.038}
    assert coalesce_subframe_scenes([scene])==[scene]


def test_tiny_asr_pause_chunks_are_merged_not_sampled_independently():
    from app.scene_analysis import merge_subframe_chunks
    chunks=[
      {"id":"a","start":0., "end":20.},
      {"id":"pause","start":20., "end":20.038},
      {"id":"b","start":20.038,"end":35.},
      {"id":"pause2","start":35., "end":35.08},
      {"id":"c","start":35.08,"end":48.}
    ]
    fixed=merge_subframe_chunks(chunks)
    assert [(x["start"],x["end"]) for x in fixed]==[(0,20.038),(20.038,35.08),(35.08,48)]
    assert len(fixed)==3
    assert chunks[1]["end"]==20.038
    assert sum(x["end"]-x["start"] for x in fixed)==48


def test_bounded_chunks_use_frame_safe_edges_and_preserve_limit(monkeypatch):
    """Regression for endless split->remerge when a candidate edge is 38 ms."""
    from app import scene_analysis
    from app import scene_detection
    from app import vision

    def units(start, end, *args, **kwargs):
        # A word boundary 38 ms after the start must never be the split edge.
        return [{"start": start, "end": min(start + .038, end)},
                {"start": start, "end": min(start + 4., end)},
                {"start": min(start + 4., end), "end": end}]
    def samples(start, end, units, *, recovery=False):
        # Emulates the visual frame budget of one inference request.
        return list(range(int((end-start)*2) + 1))
    monkeypatch.setattr(scene_detection, "analysis_chunks", lambda *args: [
        {"id": "t", "start": 0., "end": 8.}])
    monkeypatch.setattr(scene_analysis, "candidate_units", units)
    monkeypatch.setattr(vision, "inference_samples", samples)
    chunks = scene_analysis.bounded_chunks(
        {"id": "scene", "start": 0., "end": 8.}, {"segments": []}, [], max_frames=12)
    assert len(chunks) == 2
    assert chunks[0]["start"] == 0.
    assert chunks[0]["end"] == chunks[1]["start"] == 4.
    assert chunks[1]["end"] == 8.
    assert all(len(samples(x["start"], x["end"], [], recovery=True)) <= 12 for x in chunks)


def test_bounded_chunks_fail_fast_when_only_edge_is_subframe(monkeypatch):
    from app import scene_analysis, scene_detection, vision
    import pytest
    monkeypatch.setattr(scene_detection, "analysis_chunks", lambda *args: [
        {"id": "t", "start": 0., "end": 8.}])
    monkeypatch.setattr(scene_analysis, "candidate_units",
                        lambda *args, **kwargs: [{"start": 0, "end": .038},
                                                  {"start": .038, "end": 8}])
    monkeypatch.setattr(vision, "inference_samples",
                        lambda *args, **kwargs: list(range(20)))
    with pytest.raises(ValueError, match="Нет безопасной границы"):
        scene_analysis.bounded_chunks({"id": "scene", "start": 0, "end": 8},
                                      {"segments": []}, [], max_frames=12)


def test_token_ledger_skips_malformed_rows_and_does_not_abort_inference(tmp_path, monkeypatch):
    from app import token_usage
    path = tmp_path / "token-usage.jsonl"
    path.write_text('[]\nnull\nnot-json\n{"provider":"local","usage_reported":false}\n'
                    '{"provider":"deepseek","usage_reported":true,"total_tokens":77}\n',
                    encoding="utf-8")
    values = token_usage.summary(tmp_path)
    assert values["all_tokens"] == 77
    assert values["unknown_calls"] == 1
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")))
    token_usage.record(tmp_path / "nested", "local", "qwen", {"usage": {"total_tokens": 8}})


def test_partial_provider_usage_is_unknown_not_false_total(tmp_path):
    from app.token_usage import record, summary
    record(tmp_path, "local", "qwen", {"usage":{"prompt_tokens": 481}})
    usage = summary(tmp_path)
    assert usage["all_tokens"] == 0
    assert usage["unknown_calls"] == 1
    record(tmp_path, "deepseek", "chat", {
        "usage":{"prompt_tokens": 480, "completion_tokens": 20}})
    usage = summary(tmp_path)
    assert usage["all_tokens"] == 500
    assert usage["unknown_calls"] == 1



def test_corrupted_scene_cache_only_rebuilds_affected_chunk(tmp_path):
    from app.scene_analysis import _read_optional_checkpoint
    checkpoint = tmp_path / "event_0000_chunk_001.checkpoint.json"
    assert _read_optional_checkpoint(checkpoint) == {}
    for value in ('{"identity":', 'null', '[]', '{not-json}', '"wrong-type"'):
        checkpoint.write_text(value, encoding="utf-8")
        assert _read_optional_checkpoint(checkpoint) == {}
    checkpoint.write_text('{"identity":"valid","result":{}}', encoding="utf-8")
    assert _read_optional_checkpoint(checkpoint)["identity"] == "valid"


def test_frame_empty_80ms_pause_keeps_speech_and_caps_sampled_frames(tmp_path, monkeypatch):
    """Preserve the single word when the only ASR boundary has zero actual PTS."""
    from app.scene_analysis import bounded_chunks
    from app import scene_detection
    from app.vision import inference_samples, inference_storyboard
    from app import bounded_storyboard
    from app.media_probe import atomic_json

    transcript = {"segments": [{"start": .08, "end": 3.84, "text": "Реплика"}],
                  "words": [{"start": .08, "end": 3.84, "text": "Реплика"}]}
    scene = {"id": "visual", "start": 0., "end": 3.84}
    monkeypatch.setattr(scene_detection, "analysis_chunks",
                        lambda *_: [{"start": 0., "end": 3.84}])
    units = __import__("app.story_review", fromlist=["candidate_units"]).candidate_units(
        0., 3.84, transcript, [], annotated=True, max_unit_seconds=4)
    assert len(inference_samples(0, 3.84, units, recovery=True)) == 13
    # A variable-rate file can start showing frames only at 100ms.
    frames = [.1 + i * .04 for i in range(90)]
    parts = bounded_chunks(scene, transcript, [], max_frames=12, frame_times=frames)
    assert len(parts) == 1
    assert parts[0]["sampling_limit"] == 12
    assert (parts[0]["start"], parts[0]["end"]) == (0, 3.84)

    observations = []
    def fake_board(source, start, end, destination, cancelled, *, times, context):
        observations.extend(times)
        destination.write_bytes(b"source frames")
        atomic_json(destination.with_suffix(".storyboard.json"), {"frames": []})
        return times
    monkeypatch.setattr(bounded_storyboard, "build_bounded_storyboard", fake_board)
    result = inference_storyboard(tmp_path/"source.mp4",0,3.84,units,
                                  tmp_path/"board.jpg",lambda:False,
                                  recovery=True,sample_limit=parts[0]["sampling_limit"])
    assert result == observations
    assert len(result) == 12
    assert result[0] < result[-1]
