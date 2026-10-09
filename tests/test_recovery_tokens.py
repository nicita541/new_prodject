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
