"""Recoverable analysis → deterministic plan → validated local media export."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import marshal
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, MUSIC, setup_environment
from .media import choose_encoder, inspect_media, render_part, validate_export
from .planner import build_plan, validate_analysis, validate_plan, PLANNER_VERSION
from .subtitles import style_identity, make_cues, remap_words
from .editing import load_options
from .music import load_settings, pick_track, pick_track_for_part


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _timed_stage(timings: dict, stage: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings["stages_seconds"][stage] = round(time.perf_counter() - started, 6)


def _run_render_tasks(items, render, commit, cancelled, workers=2):
    """Render bounded independent batches; commit on the caller in source order.

    A failed/cancelled batch is drained before returning. Already validated
    successes are committed for resume, but no later batch is dispatched.
    """
    if workers not in (1, 2):
        raise ValueError("Допустимо не более двух параллельных частей")
    stopped = threading.Event()
    def check_cancelled():
        return stopped.is_set() or cancelled()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        try:
            for offset in range(0, len(items), workers):
                if cancelled():
                    raise InterruptedError("Обработка отменена")
                batch = items[offset:offset + workers]
                futures = [executor.submit(render, item, check_cancelled) for item in batch]
                error = None
                try:
                    pending = set(futures)
                    while pending:
                        if cancelled():
                            raise InterruptedError("Обработка отменена")
                        done, pending = concurrent.futures.wait(
                            pending, timeout=0.1, return_when=concurrent.futures.FIRST_EXCEPTION)
                        for future in done:
                            future.result()
                except BaseException as caught:
                    error = caught
                    stopped.set()
                    for future in futures:
                        future.cancel()
                    concurrent.futures.wait(futures)
                # Only the coordinator mutates checkpoints/progress. On failure
                # this still preserves completed validated parts for retry.
                for item, future in zip(batch, futures):
                    if future.cancelled() or future.exception() is not None:
                        continue
                    result = future.result()
                    try:
                        commit(item, result)
                        results.append(result)
                    except BaseException as caught:
                        error = error or caught
                if error is not None:
                    raise error
            if cancelled():
                raise InterruptedError("Обработка отменена")
        finally:
            stopped.set()
    return results


def _run_identity(job_dir: Path) -> dict:
    """Record code/settings provenance; never inspect private provider settings."""
    from .analysis import ANALYSIS_VERSION, analysis_provider, derived_story_identity
    from .editorial import load_profile
    from .pacing import PACING_VERSION
    from .deepseek import provider_identity
    from .config import ASR_MODEL, VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR
    provider = analysis_provider(job_dir)
    profile = load_profile(job_dir)
    modules = ("pipeline", "media", "analysis", "story", "closing", "pacing", "planner", "dramatic_planner",
               "part_context", "production_sequence", "source_roles", "editorial", "titles", "framing",
               "deepseek", "endings")
    semantic = derived_story_identity("recorded-in-events.meta.json", provider, profile)
    files, loaded_code = {}, {}
    for name in modules:
        path = ROOT / "app" / (name + ".py")
        files[str(path.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
        module = sys.modules.get("app." + name)
        # Loaded bytecode distinguishes a running process from files edited
        # after its imports. File hashes separately record the source snapshot.
        codes = {key: value.__code__ for key, value in vars(module).items()
                 if hasattr(value, "__code__") and getattr(value, "__module__", None) == module.__name__} if module else {}
        if module:
            for class_name, value in vars(module).items():
                if not isinstance(value, type) or value.__module__ != module.__name__:
                    continue
                for method_name, member in vars(value).items():
                    member = getattr(member, "__func__", member)
                    if hasattr(member, "__code__"):
                        codes[class_name + "." + method_name] = member.__code__
        if codes:
            loaded_code[name] = hashlib.sha256(marshal.dumps(sorted(codes.items()))).hexdigest()
    revision = None
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=3,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        value = result.stdout.strip()
        if result.returncode == 0 and len(value) == 40 and all(char in "0123456789abcdef" for char in value):
            revision = value
    except (OSError, subprocess.TimeoutExpired):
        pass
    models = []
    for path in (ASR_MODEL / "model.bin", VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR):
        if path.is_file():
            stat = path.stat()
            models.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"),
                           "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return {"git_commit": revision, "source_files_sha256": files,
            "loaded_function_bytecode_sha256": loaded_code, "python_version": sys.version.split()[0],
            "analysis_version": ANALYSIS_VERSION, "planner_version": PLANNER_VERSION, "renderer_version": 6,
            "pacing_version": PACING_VERSION, "semantic_identity": semantic,
            "provider": provider_identity(provider), "editorial_profile": profile,
            "editing": load_options(job_dir), "music": load_settings(), "model_files": models}


def _archive_obsolete_outputs(job_dir: Path, previous: dict | None, current: dict, cancelled) -> None:
    """Move only obsolete, checkpoint-verified exports after successful render."""
    if not isinstance(previous, dict) or not previous.get("fingerprint"):
        return
    retained = {part["index"] for part in current["parts"]}
    output = (job_dir / "output").resolve()
    output.relative_to(job_dir)
    candidates = []
    for part in previous.get("parts", []):
        if not isinstance(part, dict):
            continue
        index = part.get("index")
        if type(index) is not int or index < 1 or index in retained:
            continue
        name = f"part_{index:03}"
        checkpoint = (job_dir / "render" / (name + ".json")).resolve()
        checkpoint.relative_to(job_dir)
        video, subtitles = output / (name + ".mp4"), output / (name + ".srt")
        if video.is_symlink() or subtitles.is_symlink():
            continue
        for path in (video, subtitles):
            path.resolve().relative_to(output)
        try:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                continue
            if (saved.get("fingerprint") != previous["fingerprint"] or not video.is_file()
                    or saved.get("size") != video.stat().st_size
                    or saved.get("mtime_ns") != video.stat().st_mtime_ns
                    or not subtitles.is_file()
                    or saved.get("srt_hash") != hashlib.sha256(subtitles.read_bytes()).hexdigest()):
                continue
        except (OSError, ValueError, TypeError):
            continue
        candidates.append((video.resolve(), subtitles.resolve(), saved))
    if not candidates:
        return
    if cancelled():
        raise InterruptedError("Обработка отменена")
    archive = (job_dir / "previous_exports" / uuid.uuid4().hex).resolve()
    archive.relative_to(job_dir)
    archive.mkdir(parents=True)
    _atomic_json(archive / "plan.json", previous)
    for video, subtitles, saved in candidates:
        if cancelled():
            raise InterruptedError("Обработка отменена")
        _atomic_json(archive / (video.stem + ".checkpoint.json"), saved)
        for source in (video, subtitles):
            destination = (archive / source.name).resolve()
            source.relative_to(output)
            destination.relative_to(archive)
            os.replace(source, destination)


def run_job(job_dir: Path, report, cancelled) -> list[str]:
    job_dir = job_dir.resolve()
    job_dir.relative_to(ROOT.resolve())
    timings = {"version": 1, "status": "running", "render_workers": 2,
               "started_at": datetime.now(timezone.utc).isoformat(),
               "stages_seconds": {}, "parts": []}
    run_id = uuid.uuid4().hex
    timings["run_id"] = run_id
    manifest_path = job_dir / "runs" / (run_id + ".json")
    started = time.perf_counter()
    failed = False
    from .pipeline_diagnostics import Diagnostics
    diagnostics = Diagnostics(job_dir)
    diagnostics.start(job_id=job_dir.name)
    active = {'stage': None, 'started': time.perf_counter()}

    def close_stage():
        if active['stage']:
            diagnostics.event(active['stage'], 'end', elapsed_seconds=round(time.perf_counter()-active['started'], 6))

    def audited_report(stage, progress, message):
        if stage != active['stage']:
            close_stage()
            active.update(stage=stage, started=time.perf_counter())
            diagnostics.event(stage, 'start', progress=progress, message=message)
        report(stage, progress, message)

    try:
        timings["identity"] = _run_identity(job_dir)
        _atomic_json(manifest_path, timings)
        outputs = _run_job(job_dir, audited_report, cancelled, timings)
        timings["status"] = "completed"
        return outputs
    except BaseException as error:
        failed = True
        timings["status"] = "cancelled" if isinstance(error, InterruptedError) else "failed"
        timings["error_type"] = type(error).__name__
        try:
            diagnostics.event(active['stage'] or 'pipeline', 'exception', error_type=type(error).__name__, error=str(error))
        except OSError as diagnostic_error:
            error.add_note('Diagnostic write failed: '+str(diagnostic_error))
        raise
    finally:
        try:
            close_stage()
            diagnostics.event('pipeline', 'end', status=timings['status'], elapsed_seconds=round(time.perf_counter()-started, 6))
            previous_run = json.loads((diagnostics.path/'run.json').read_text(encoding='utf-8'))
            diagnostics.write('run.json', {**previous_run, 'job_id': job_dir.name, 'status': timings['status']})
        except OSError:
            if not failed:
                raise
        timings["finished_at"] = datetime.now(timezone.utc).isoformat()
        timings["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        timings["parts"].sort(key=lambda part: part["index"])
        try:
            _atomic_json(manifest_path, timings)
            _atomic_json(job_dir / "timings.json", timings)
        except OSError:
            # Diagnostic persistence must not obscure the pipeline's original
            # error/cancellation. A successful job still requires its manifest.
            if not failed:
                raise


def _run_job(job_dir: Path, report, cancelled, timings: dict) -> list[str]:
    from .analysis import analyze
    setup_environment()
    job_dir = job_dir.resolve()
    job_dir.relative_to(ROOT.resolve())
    source_info = json.loads((job_dir / "source.json").read_text(encoding="utf-8"))
    source = Path(source_info["path"]).resolve()
    source.relative_to(ROOT.resolve())
    if source.suffix.lower() not in {".mp4", ".mkv"} or not source.is_file():
        raise ValueError("Исходная серия не найдена или не поддерживается")
    def check():
        if cancelled():
            raise InterruptedError("Обработка отменена")
    check()
    options = load_options(job_dir)
    music_config = load_settings()
    with _timed_stage(timings, "analysis"):
        analysis = analyze(job_dir, source, report, cancelled)
    check()
    from .editorial import load_profile
    editorial_prof = load_profile(job_dir)
    stat = source.stat()
    from .semantic_identity import semantic_identity
    identity = {"analysis": analysis, "source": {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
                "semantic_components": semantic_identity(),
                "planner_version": PLANNER_VERSION, "renderer_version": 6, "editing": options,
                "editorial_profile": editorial_prof,
                "music": music_config,
                "subtitle_style": style_identity(options['caption_style'])}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    plan_path = job_dir / "plan.json"
    plan = None
    previous_plan = None
    unfinished_plan = None
    previous_path = (job_dir / "output" / "plan.json").resolve()
    previous_path.relative_to(job_dir)
    if previous_path.is_file():
        try:
            previous_plan = json.loads(previous_path.read_text(encoding="utf-8"))
        except (ValueError, TypeError):
            pass
    if plan_path.is_file():
        try:
            cached = json.loads(plan_path.read_text(encoding="utf-8"))
            unfinished_plan = cached
            if previous_plan is None:
                previous_plan = cached
            if cached.get("fingerprint") == fingerprint:
                validate_plan(cached, analysis)
                plan = cached
        except (ValueError, KeyError, TypeError):
            pass
    planning_cache_hit = plan is not None
    planning_started = time.perf_counter()
    if plan is None:
        report("planning", 0.67, "Собираем последовательность событий и целые реплики")
        from .editorial import load_profile
        editorial_prof = load_profile(job_dir)
        if editorial_prof.get('dramatic_condensation', False):
            from .dramatic_planner import build_dramatic_plan
            plan = build_dramatic_plan(analysis)
        else:
            plan = build_plan(analysis)
        plan['editing'] = options
        for part in plan['parts']:
            part.update(options)
            if options['caption_style'] == 'accent':
                part['subtitles'] = make_cues(remap_words(analysis['transcript']['words'], part['cuts']), 'accent')
        validate_plan(plan, analysis)
        plan["source"]["name"] = source_info.get("name", source.name)
        plan["fingerprint"] = fingerprint
        _atomic_json(plan_path, plan)
    timings["stages_seconds"]["planning"] = round(time.perf_counter() - planning_started, 6)
    from .pipeline_diagnostics import Diagnostics
    diagnostics = Diagnostics(job_dir)
    diagnostics.summary(selected_events=len(plan.get('selected_event_ids', [])), parts=len(plan['parts']),
                        cuts=sum(len(p['cuts']) for p in plan['parts']),
                        final_duration=sum(p['duration'] for p in plan['parts']), warnings=len(plan.get('warnings', [])))
    diagnostics.write('planner.json', {'cache_hit': planning_cache_hit,
        'episode_profile': plan.get('episode_profile', analysis.get('episode_profile')),
        'retention_budget': plan.get('retention_budget'),
        'budget_exceeded': plan.get('retention_budget_exceeded', False),
        'selected_event_ids': plan.get('selected_event_ids', []),
        'parts': [{'index': p['index'], 'duration': p['duration'], 'ending': p.get('ending')} for p in plan['parts']]})
    planner_debug = plan.get('planner_diagnostics', {})
    if planner_debug:
        diagnostics.write('planner.json', {**planner_debug, 'cache_hit': planning_cache_hit,
                                          'semantic_components': identity['semantic_components']})
        for decision in planner_debug.get('decisions', []):
            diagnostics.append('decisions.jsonl', {'stage': 'planning', **decision})
    for warning in plan.get('warnings', []):
        diagnostics.warning('planning', str(warning))
    from .part_context import generate as generate_part_context
    with _timed_stage(timings, 'part_context'):
        generate_part_context(plan, job_dir, report, cancelled)
        _atomic_json(plan_path, plan)
    workdir, output_dir = job_dir / "render", job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    missing = []
    rendering_started = time.perf_counter()
    music_tracks_assigned = {}
    if music_config.get("enabled"):
        for part in plan["parts"]:
            track = pick_track_for_part(MUSIC, music_config, part["index"], len(plan["parts"]))
            if track is not None:
                music_tracks_assigned[part["index"]] = track

    timings["music"] = {
        "enabled": music_config["enabled"],
        "volume": music_config["volume"],
        "mode": music_config.get("mode", "random_per_part"),
        "tracks": {str(k): v.name for k, v in music_tracks_assigned.items()},
        "fade_in": bool(music_config.get("fade_in", True)),
        "fade_out": bool(music_config.get("fade_out", True)),
    }
    if not music_config["enabled"]:
        report("rendering", 0.7, "Background music: disabled")
    elif not music_tracks_assigned:
        report("rendering", 0.7, "Background music: skipped (no audio files in music folder)")
    else:
        volume_pct = int(round(music_config["volume"] * 100))
        unique_names = sorted({t.name for t in music_tracks_assigned.values()})
        tracks_desc = ", ".join(unique_names[:3]) + ("..." if len(unique_names) > 3 else "")
        mode_label = ("случайный для каждого фрагмента" if music_config.get("mode") == "random_per_part"
                      else "один трек" if music_config.get("mode") == "single"
                      else "по фрагментам")
        report("rendering", 0.7,
               f"Background music:\nmode={mode_label}\nvolume={volume_pct}%\n"
               f"active_tracks={len(unique_names)} ({tracks_desc})\n"
               f"fade_in={'true' if music_config.get('fade_in', True) else 'false'}\n"
               f"fade_out={'true' if music_config.get('fade_out', True) else 'false'}")
    for part in plan["parts"]:
        check()
        started = time.perf_counter()
        name = f"part_{part['index']:03}.mp4"
        path = output_dir / name
        checkpoint = workdir / f"part_{part['index']:03}.json"
        valid = False
        if path.is_file() and checkpoint.is_file() and path.with_suffix(".srt").is_file():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                if (saved.get("fingerprint") == fingerprint and saved.get("size") == path.stat().st_size
                        and saved.get("mtime_ns") == path.stat().st_mtime_ns
                        and saved.get("srt_hash") == hashlib.sha256(path.with_suffix(".srt").read_bytes()).hexdigest()):
                    validate_export(path, part["duration"], workdir, cancelled,
                                    max_duration=150.0 if part.get("duration", 0) > 120.0 else None)
                    valid = True
            except (ValueError, KeyError, RuntimeError):
                pass
        if valid:
            timings["parts"].append({"index": part["index"], "cached": True,
                                     "encoder": saved.get("encoder"),
                                     "seconds": round(time.perf_counter() - started, 6)})
        else:
            missing.append(part)
        outputs.extend([name, path.with_suffix(".srt").name])
    try:
        if missing:
            encoder = choose_encoder(workdir, cancelled)
            timings["encoder"] = encoder
            completed = len(plan["parts"]) - len(missing)
            report("rendering", 0.7 + 0.29 * completed / len(plan["parts"]),
                   f"Создаём оставшиеся части: {len(missing)}")
            def render(part, task_cancelled):
                started = time.perf_counter()
                background_music = None
                p_track = music_tracks_assigned.get(part["index"])
                if p_track is not None:
                    from .audio_analysis import detect_transcript_music_intervals, map_cuts_to_part_duck_intervals
                    source_music = detect_transcript_music_intervals(analysis.get("transcript", {}))
                    duck_intervals = map_cuts_to_part_duck_intervals(part["cuts"], source_music) if music_config.get("smart_ducking", True) else []
                    background_music = {"path": p_track, "volume": music_config["volume"],
                                        "volume_music_duck": music_config.get("volume_music_duck", 0.015),
                                        "duck_intervals": duck_intervals,
                                        "fade_in": music_config.get("fade_in", True),
                                        "fade_out": music_config.get("fade_out", True)}
                path = render_part(source, part, analysis["probe"], output_dir,
                                   workdir / f"part_{part['index']:03}", encoder, task_cancelled,
                                   background_music=background_music)
                metadata = workdir / f"part_{part['index']:03}" / "render-info.json"
                actual_encoder = json.loads(metadata.read_text(encoding="utf-8")).get("encoder") if metadata.is_file() else None
                return {"path": path, "encoder": actual_encoder,
                        "seconds": round(time.perf_counter() - started, 6),
                        "music_track": p_track.name if p_track else None}
            def commit(part, result):
                nonlocal completed
                path = result["path"]
                checkpoint = workdir / f"part_{part['index']:03}.json"
                _atomic_json(checkpoint, {"fingerprint": fingerprint, "size": path.stat().st_size,
                                          "mtime_ns": path.stat().st_mtime_ns,
                                          "encoder": result["encoder"], "requested_encoder": encoder,
                                          "run_id": timings["run_id"],
                                          "music_track": result.get("music_track"),
                                          "srt_hash": hashlib.sha256(path.with_suffix(".srt").read_bytes()).hexdigest()})
                part["music_track"] = result.get("music_track")
                timings["parts"].append({"index": part["index"], "cached": False,
                                         "encoder": result["encoder"],
                                         "seconds": result["seconds"]})
                completed += 1
                report("rendering", 0.7 + 0.29 * completed / len(plan["parts"]),
                       f"Создана часть {part['index']} из {len(plan['parts'])}")
            _run_render_tasks(missing, render, commit, cancelled)
        else:
            report("rendering", 0.99, f"Проверены все части: {len(plan['parts'])}")
    finally:
        timings["stages_seconds"]["rendering"] = round(time.perf_counter() - rendering_started, 6)
    check()
    _archive_obsolete_outputs(job_dir, previous_plan, plan, cancelled)
    if unfinished_plan != previous_plan:
        _archive_obsolete_outputs(job_dir, unfinished_plan, plan, cancelled)
    _atomic_json(output_dir / "plan.json", plan)
    report("completed", 1.0, f"Готово: {len(plan['parts'])} частей. Проверьте сюжет и кадрирование в просмотре.")
    return outputs
