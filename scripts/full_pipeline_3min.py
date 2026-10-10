"""Three-minute end-to-end KADR verification. All generated files stay inside ROOT.

Offline: genuine 180 s MP4 -> real probe/planner/FFmpeg/music/subtitles ->
        re-run validated cache -> tampered SRT -> real re-render -> finishing.
        Only the semantic/ASR *decision* is a deterministic fixture.
Real:    genuine production Whisper + local VLM + planner + export.
        No stubbed semantic decisions. Requires local models; can fail quality gates.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import config
from app.media import run_command, validate_export
from app.media_probe import probe_media
from app.pipeline import run_job
from app.jobs import atomic_json
from app.subtitles import write_srt


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_step(report: dict, name: str, function):
    begun = time.monotonic()
    try:
        result = function()
    except BaseException as error:
        report["checks"].append({"name": name, "status": "failed",
                                 "seconds": round(time.monotonic() - begun, 3),
                                 "error_type": type(error).__name__, "error": str(error)})
        print(f"[FAIL] {name}: {type(error).__name__}: {error}", flush=True)
        raise
    report["checks"].append({"name": name, "status": "passed",
                             "seconds": round(time.monotonic() - begun, 3)})
    print(f"[PASS] {name}", flush=True)
    return result


def generate_video(directory: Path) -> Path:
    """Real decodable, timestamped 180-second test video and audio.

    Test patterns contain moving pixels and timed audio, but are NOT a real
    story and do NOT simulate spoken Russian dialogue.
    """
    source = directory / "source-180s.mp4"
    if source.is_file():
        media = probe_media(source)
        if 179.8 <= float(media["duration"]) <= 180.2 and media["has_audio"]:
            return source
    run_command([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=180",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=180",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k",
        "-movflags", "+faststart", str(source)], directory, timeout=600)
    return source


def fixture_analysis(source: Path) -> dict:
    """Offline analysis substitute: explicit truthful test fixture, no AI."""
    probe = probe_media(source)
    words, segments, events = [], [], []
    for index in range(6):
        start = index * 30.0
        left, right = start + 3, start + 5.5
        # The text is a synthetic subtitle fixture, NOT speech recognized in
        # the sine-wave soundtrack. Kept to check timeline remapping.
        word = {"start": left, "end": right, "text": f"Проверка сцены {index+1}."}
        words.append(word)
        segments.append(dict(word))
        events.append({"id": f"fixture_{index:02d}", "start": start, "end": start+30,
                       "kind": "story", "importance": 4, "summary": "Synthetic QA interval",
                       "requires": [], "focus": [], "unit_selection_version": 1,
                       "selected_ranges": [{"start": start+2.5, "end": start+6}]})
    return {"probe": probe, "duration": float(probe["duration"]),
            "transcript": {"words": words, "segments": segments},
            "shots": [], "events": events,
            "synthetic_semantic_fixture": True}


def write_progress(job: Path, report: dict, phase: str):
    progress = job / "e2e-progress.jsonl"
    progress.parent.mkdir(parents=True, exist_ok=True)
    def record(stage, percent, message):
        row = {"phase": phase, "stage": stage, "progress": percent, "message": message}
        with progress.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
        report["pipeline_stages"].append(row)
        print(f"[{phase}] {stage} {percent:.0%} {message[:90]}", flush=True)
    return record


def verify_outputs(job: Path, names: list[str], analysis: dict) -> dict:
    from app.planner import validate_plan
    plan = json.loads((job / "plan.json").read_text("utf-8"))
    validate_plan(plan, analysis)
    assert len(plan["parts"]) >= 1, "Montage plan did not produce any Shorts"
    expected = sorted([name for part in plan["parts"]
                       for name in (f"part_{part['index']:03}.mp4",
                                    f"part_{part['index']:03}.srt")])
    assert sorted(names) == expected, f"Output list mismatch: {names!r}"
    details = []
    for part in plan["parts"]:
        stem = f"part_{part['index']:03}"
        mp4, srt = job / "output" / (stem + ".mp4"), job / "output" / (stem + ".srt")
        assert mp4.stat().st_size > 10000 and srt.is_file(), stem
        info = validate_export(mp4, part["duration"], job / "e2e-probe")
        assert info, f"Media validation returned no metadata for {stem}"
        decoded = probe_media(mp4)
        assert decoded["has_audio"], f"No source/dialogue audio in {stem}"
        assert part["duration"] <= 120, f"Short longer than 120 seconds: {stem}"
        assert srt.read_text("utf-8").strip(), f"Empty subtitles in {stem}"
        details.append({"part": part["index"], "duration": part["duration"],
                        "mp4_sha256": sha(mp4), "srt_sha256": sha(srt),
                        "file_size": mp4.stat().st_size})
    return {"plan_parts": len(plan["parts"]), "files": details, "plan": plan}


def run_offline(root: Path, report: dict) -> None:
    from app import pipeline
    from app import studio_render
    from app.finishing import FinishProfile
    # This job is isolated from real projects; no user data is modified.
    job = root / "jobs" / str(uuid.uuid4())
    job.mkdir(parents=True)
    source = inspect_step(report, "generate_true_180_second_mp4",
                          lambda: generate_video(root))
    report["source"] = {"path": str(source), "sha256": sha(source)}
    analysis = inspect_step(report, "ffprobe_source_and_prepare_decision_fixture",
                            lambda: fixture_analysis(source))
    assert 179.8 <= analysis["probe"]["duration"] <= 180.2
    assert analysis["probe"]["has_audio"]
    atomic_json(job / "source.json", {"path": str(source), "name": source.name})
    atomic_json(job / "render-settings.json", {"layout": "cinema", "caption_style": "classic"})
    report["analysis_mode"] = "deterministic_semantic_fixture_NOT_ASR_OR_VLM"
    report["job_dir"] = str(job)
    music = root / "qa-music"
    music.mkdir(parents=True, exist_ok=True)
    track = music / "qa-tone.wav"
    if not track.is_file():
        run_command([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-f", "lavfi", "-i", "sine=frequency=280:sample_rate=16000:duration=8",
                     "-c:a", "pcm_s16le", str(track)], root)
    song = {"enabled": True, "volume": .15, "track": track.name, "mode": "single",
            "part_tracks": {}, "fade_in": True, "fade_out": True,
            "smart_ducking": False, "volume_music_duck": .015}
    # Offline fixture is a moving test card and a sine tone, not a story:
    # normal source-proved quality gating must reject it. Bypass the semantic
    # *decision* only in this explicitly labelled mechanical run; retain the
    # real gate's actual findings in the report. Real mode never bypasses it.
    from app import final_quality
    real_gate = final_quality.inspect_final_quality
    report["quality_gate_mode"] = "synthetic_fixture_only; real mode enforces source-proved gate"
    def fixture_gate(value, plan=None):
        result = real_gate(value, plan)
        report.setdefault("real_gate_inspections", []).append({
            "phase": "before_render" if plan is not None else "before_planner",
            "status": result["status"],
            "problem_codes": sorted({p["code"] for p in result.get("problems", [])})})
        if result["status"] == "passed":
            return result
        return {**result, "status": "passed", "problems": [],
                "synthetic_fixture_override": True}

    # Only inference and the synthetic-only editorial decision are substituted.
    # Media decode, planning, timestamp remap, FFmpeg and caching remain real.
    with patch("app.analysis.analyze", return_value=analysis), \
         patch("app.final_quality.inspect_final_quality", side_effect=fixture_gate), \
         patch.object(pipeline, "load_settings", return_value=song), \
         patch.object(pipeline, "MUSIC", music), \
         patch.object(pipeline, "choose_encoder", return_value="libx264"), \
         patch.object(studio_render.config, "MUSIC", music):
        names = inspect_step(report, "real_pipeline_plan_and_ffmpeg_render",
                             lambda: run_job(job, write_progress(job, report, "first"), lambda: False))
        first = inspect_step(report, "decode_validate_mp4_audio_srt_and_plan",
                             lambda: verify_outputs(job, names, analysis))
        report["first_output"] = first["files"]
        assert any(part["subtitles"] for part in first["plan"]["parts"])
        assert all(part.get("music_track") == track.name for part in first["plan"]["parts"])
        report["music"] = {"file": track.name, "volume": .15, "mode": "single"}
        names_again = inspect_step(report, "second_full_pipeline_run_for_cache",
                                  lambda: run_job(job, write_progress(job, report, "cached"), lambda: False))
        assert names_again == names
        cached = json.loads((job / "timings.json").read_text("utf-8"))
        assert all(p["cached"] for p in cached["parts"]), "Video cache not used on second run"
        after = verify_outputs(job, names_again, analysis)
        assert after["files"] == first["files"], "Cached MP4 or SRT changed"
        report["cache"] = {"all_parts_reused": True, "parts": len(cached["parts"])}
        # Deliberate damage: a valid source output must be invalidated if the
        # SRT sidecar hash no longer matches the checkpoint.
        part = first["plan"]["parts"][0]
        srt = job / "output" / f"part_{part['index']:03}.srt"
        srt.write_text("INVALIDATED_BY_3MIN_E2E", encoding="utf-8")
        rerun = inspect_step(report, "invalidate_corrupted_subtitles_and_rerender",
                             lambda: run_job(job, write_progress(job, report, "rebuild"), lambda: False))
        refreshed = json.loads((job / "timings.json").read_text("utf-8"))
        assert not next(p for p in refreshed["parts"] if p["index"] == part["index"])["cached"]
        assert "INVALIDATED_BY_3MIN_E2E" not in srt.read_text("utf-8")
        verify_outputs(job, rerun, analysis)
        report["cache"]["corrupt_srt_forced_rerender"] = True
        # Isolated real finishing export (video overlays/music), no API/model.
        manager = SimpleNamespace(root=ROOT, job_dir=lambda _: job)
        profile = FinishProfile().model_dump()
        profile["audio"].update({"enabled": True, "mode": "single",
                                 "track": track.name, "volume": .15})
        profile["video"]["zoom"] = 90
        index = first["plan"]["parts"][0]["index"]
        # Use an edited job-scoped caption, not episode-global text.
        cap_dir = job / "finishing"
        cap_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(cap_dir / f"captions_{index:03}.json",
                    {"job_id": job.name, "part_index": index, "revision": 1,
                     "cues": [{"start": .1, "end": 1.6, "text": "ГОТОВО: QA"}]})
        from app.studio_render import render_finishing_part
        target = inspect_step(report, "ffmpeg_finishing_zoom_music_and_edited_captions",
            lambda: render_finishing_part(manager, job.name, first["plan"]["parts"][0],
                profile, job / "finished", job / "finished-work", preview=(0, 2.0)))
        assert target.is_file() and target.stat().st_size > 10000
        sidecar = target.with_suffix(".srt")
        assert "ГОТОВО: QA" in sidecar.read_text("utf-8")
        assert probe_media(target)["has_audio"]
        report["finished_preview"] = {"path": str(target), "sha256": sha(target)}
    assert sha(source) == report["source"]["sha256"], "Original 180s source was changed"


def run_real(root: Path, report: dict, source_arg: Path | None, transcript_arg: Path | None) -> None:
    from scripts.run_production_raw_quality import run as production_run
    # This path does not patch any inference model or semantic stage.
    # Actual content must have a storyline and speech; a synthetic test card
    # cannot satisfy the source-grounded semantic quality gate.
    if source_arg is None:
        raise ValueError("Real-model mode requires --source with a 180s story video")
    source = source_arg.resolve()
    source.relative_to(ROOT.resolve())
    actual = probe_media(source)
    assert 179.8 <= float(actual["duration"]) <= 180.2, "Real mode expects a 180s input"
    assert actual["has_audio"], "Input has no audio"
    inp = root / "real-input"
    inp.mkdir(parents=True, exist_ok=True)
    entry = {"source": str(source)}
    if transcript_arg:
        transcript_arg = transcript_arg.resolve()
        transcript_arg.relative_to(ROOT.resolve())
        entry["transcript"] = str(transcript_arg)
    atomic_json(inp / "input.json", entry)
    report["analysis_mode"] = "real_local_whisper_and_vision" if not transcript_arg else "provided_asr_and_real_local_vision"
    report["source"] = {"path": str(source), "sha256": sha(source)}
    job = root / "real-job"
    outcome = inspect_step(report, "genuine_production_analysis_to_final_mp4",
                           lambda: production_run(inp, job, render=True))
    if not outcome["complete"]:
        raise RuntimeError("Production quality gate did not pass; see observed-outcome.json")
    assert outcome["actual_model_requests"] > 0, "Real mode made zero model requests"
    report["real_model_requests"] = outcome["actual_model_requests"]
    from app.media_probe import load_json
    first_outputs = {name: sha(job / "output" / name) for name in outcome["outputs"]}
    first_calls = outcome["actual_model_requests"]
    # A completed real-model run must be resumable with no additional model
    # inference or FFmpeg encode when the source and settings are unchanged.
    second = inspect_step(report, "genuine_model_and_video_cache_resume",
                          lambda: production_run(inp, job, render=True))
    if not second["complete"]:
        raise RuntimeError("The resumed production quality gate is unresolved")
    if second["actual_model_requests"] != first_calls:
        raise AssertionError("Real model cache miss: new inference requests were made")
    if not all(part["cached"] for part in load_json(job / "timings.json")["parts"]):
        raise AssertionError("Real FFmpeg export cache did not reuse all parts")
    for name, fingerprint in first_outputs.items():
        if sha(job / "output" / name) != fingerprint:
            raise AssertionError("Real export changed after cache hit: " + name)
    report["real_resume"] = {"model_requests_unchanged": True,
                             "all_render_parts_cached": True,
                             "identical_output_hashes": True}
    events = job / "observed-progress.jsonl"
    if events.is_file():
        report["pipeline_stages"] = [json.loads(row) for row in
            events.read_text("utf-8").splitlines() if row.strip()][-500:]
    assert sha(source) == report["source"]["sha256"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "real"), default="offline")
    parser.add_argument("--source", type=Path, help="Real mode: existing 180s video inside project")
    parser.add_argument("--transcript", type=Path, help="Real mode: optional ordinary ASR JSON inside project")
    parser.add_argument("--directory", type=Path, help="Output directory inside project/temp")
    args = parser.parse_args(argv)
    config.setup_environment()
    if not config.FFMPEG.is_file() or not config.FFPROBE.is_file():
        parser.error("FFmpeg and FFprobe must be installed in tools/ffmpeg/bin")
    directory = (args.directory or
                 (config.TEMP / "full-pipeline-3min" /
                  (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]))).resolve()
    try:
        directory.relative_to(config.TEMP.resolve())
    except ValueError:
        parser.error("--directory must be inside project/temp")
    directory.mkdir(parents=True, exist_ok=True)
    report = {"mode": args.mode, "duration_seconds": 180, "status": "running",
              "checks": [], "pipeline_stages": [],
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "report_path": str(directory / "report.json")}
    try:
        if args.mode == "offline":
            run_offline(directory, report)
        else:
            run_real(directory, report, args.source, args.transcript)
        report["status"] = "passed"
        return_code = 0
    except BaseException as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        print(f"[FAIL] full pipeline: {type(error).__name__}: {error}", flush=True)
        return_code = 1
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(directory / "report.json", report)
        print("Machine-readable report: " + str(directory / "report.json"), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
