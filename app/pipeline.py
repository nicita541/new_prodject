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

from .config import ROOT, setup_environment
from .media import choose_encoder, render_part, validate_export
from .planner import build_plan, validate_analysis, validate_plan
from .subtitles import style_identity, make_cues, remap_words
from .editing import load_options


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
    modules = ("pipeline", "media", "analysis", "story", "closing", "pacing", "planner",
               "production_sequence", "source_roles", "editorial", "titles", "framing", "deepseek")
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
            "analysis_version": ANALYSIS_VERSION, "planner_version": 9, "renderer_version": 5,
            "pacing_version": PACING_VERSION, "semantic_identity": semantic,
            "provider": provider_identity(provider), "editorial_profile": profile,
            "editing": load_options(job_dir), "model_files": models}


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
    try:
        timings["identity"] = _run_identity(job_dir)
        _atomic_json(manifest_path, timings)
        outputs = _run_job(job_dir, report, cancelled, timings)
        timings["status"] = "completed"
        return outputs
    except BaseException as error:
        failed = True
        timings["status"] = "cancelled" if isinstance(error, InterruptedError) else "failed"
        timings["error_type"] = type(error).__name__
        raise
    finally:
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
    with _timed_stage(timings, "analysis"):
        analysis = analyze(job_dir, source, report, cancelled)
    check()
    validate_analysis(analysis)
    stat = source.stat()
    identity = {"analysis": analysis, "source": {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
                "planner_version": 9, "renderer_version": 5, "editing": options,
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
    planning_started = time.perf_counter()
    if plan is None:
        report("planning", 0.67, "Собираем последовательность событий и целые реплики")
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
    workdir, output_dir = job_dir / "render", job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    missing = []
    rendering_started = time.perf_counter()
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
                    validate_export(path, part["duration"], workdir, cancelled)
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
                path = render_part(source, part, analysis["probe"], output_dir,
                                   workdir / f"part_{part['index']:03}", encoder, task_cancelled)
                metadata = workdir / f"part_{part['index']:03}" / "render-info.json"
                actual_encoder = json.loads(metadata.read_text(encoding="utf-8")).get("encoder") if metadata.is_file() else None
                return {"path": path, "encoder": actual_encoder,
                        "seconds": round(time.perf_counter() - started, 6)}
            def commit(part, result):
                nonlocal completed
                path = result["path"]
                checkpoint = workdir / f"part_{part['index']:03}.json"
                _atomic_json(checkpoint, {"fingerprint": fingerprint, "size": path.stat().st_size,
                                          "mtime_ns": path.stat().st_mtime_ns,
                                          "encoder": result["encoder"], "requested_encoder": encoder,
                                          "run_id": timings["run_id"],
                                          "srt_hash": hashlib.sha256(path.with_suffix(".srt").read_bytes()).hexdigest()})
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
