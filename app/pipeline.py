"""Recoverable analysis → deterministic plan → validated local media export."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
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
    analysis = analyze(job_dir, source, report, cancelled)
    check()
    validate_analysis(analysis)
    stat = source.stat()
    identity = {"analysis": analysis, "source": {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
                "planner_version": 8, "renderer_version": 4, "editing": options,
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
    workdir, output_dir = job_dir / "render", job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    encoder = None
    outputs = []
    for index, part in enumerate(plan["parts"]):
        check()
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
        report("rendering", 0.7 + 0.29 * index / len(plan["parts"]),
               f"{'Проверена' if valid else 'Создаём'} часть {part['index']} из {len(plan['parts'])}")
        if not valid:
            encoder = encoder or choose_encoder(workdir, cancelled)
            path = render_part(source, part, analysis["probe"], output_dir,
                               workdir / f"part_{part['index']:03}", encoder, cancelled)
            _atomic_json(checkpoint, {"fingerprint": fingerprint, "size": path.stat().st_size,
                                      "mtime_ns": path.stat().st_mtime_ns,
                                      "srt_hash": hashlib.sha256(path.with_suffix(".srt").read_bytes()).hexdigest()})
        outputs.extend([name, path.with_suffix(".srt").name])
    check()
    _archive_obsolete_outputs(job_dir, previous_plan, plan, cancelled)
    if unfinished_plan != previous_plan:
        _archive_obsolete_outputs(job_dir, unfinished_plan, plan, cancelled)
    _atomic_json(output_dir / "plan.json", plan)
    report("completed", 1.0, f"Готово: {len(plan['parts'])} частей. Проверьте сюжет и кадрирование в просмотре.")
    return outputs
