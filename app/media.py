"""Local FFmpeg execution, validated atomic exports and smooth portrait framing."""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import time
import uuid
from pathlib import Path

from .config import FFMPEG, FFPROBE, ROOT
from .subtitles import write_ass, write_srt
from .planner import MAX_DURATION

_FRAME_BOUNDS = {}
EXPORT_VALIDATION_VERSION = 1

# A render may spend time opening several source intervals before the first
# output frame. Once it starts, only advancing media (not diagnostic log writes)
# keeps it alive. These are conservative infrastructure defaults, not measured
# performance targets; the effective policy is logged for later calibration.
_RENDER_BOOTSTRAP_SECONDS = 180.0
_RENDER_STALL_SECONDS = 120.0
_RENDER_SECONDS_PER_OUTPUT_SECOND = 120.0


def video_frame_bounds(source: Path, workdir: Path, cancelled=lambda: False) -> tuple[float, float]:
    """Actual video timestamps, independent of an audio/container EOF tail."""
    if cancelled():
        raise InterruptedError('Обработка отменена')
    source = source.resolve()
    stat = source.stat()
    key = (str(source), stat.st_size, stat.st_mtime_ns)
    if key in _FRAME_BOUNDS:
        return _FRAME_BOUNDS[key]
    info = inspect_media(source, workdir, cancelled)
    video = next((stream for stream in info.get('streams', []) if stream.get('codec_type') == 'video'), None)
    if video is None:
        raise ValueError('Источник не содержит видео')
    first = float(video.get('start_time', 0))
    duration = float(video.get('duration', info.get('format', {}).get('duration', 0)))
    if not math.isfinite(first) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Не удалось определить границы исходного видео')
    end = first + duration
    frames = json.loads(run_command([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0',
        '-read_intervals', f'{max(first, end-5):.6f}%{end+1:.6f}',
        '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(source)],
        workdir, cancelled, 45))
    times = [float(frame['best_effort_timestamp_time']) for frame in frames.get('frames', [])
             if frame.get('best_effort_timestamp_time') is not None]
    times = [timestamp for timestamp in times if math.isfinite(timestamp) and timestamp >= first]
    if not times:
        raise ValueError('Не удалось прочитать последние исходные видеокадры')
    bounds = (first, max(times))
    _FRAME_BOUNDS[key] = bounds
    return bounds


def run_command(argv: list[str], cwd: Path, cancelled=lambda: False, timeout: float | None = None, *, on_tick=None) -> str:
    cwd.mkdir(parents=True, exist_ok=True)
    log = cwd / ("process_" + uuid.uuid4().hex + ".log")
    if cancelled():
        raise InterruptedError("Обработка отменена")
    started = time.monotonic()
    process_log = str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else log.name
    tool = Path(argv[0]).name
    logging.getLogger("app.media").info(
        "External tool started: %s", tool,
        extra={"action": "process_start", "stage": "media", "tool_name": tool,
               "detail_log": process_log})
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with log.open("wb") as stderr:
        process = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), stdout=subprocess.PIPE,
                                   stderr=stderr, shell=False, creationflags=flags)
        try:
            while True:
                if cancelled():
                    raise InterruptedError("Обработка отменена")
                if timeout and time.monotonic() - started > timeout:
                    raise TimeoutError("Превышено время выполнения " + Path(argv[0]).name)
                try:
                    output, _ = process.communicate(timeout=0.2)
                    if on_tick:
                        on_tick()
                    break
                except subprocess.TimeoutExpired:
                    if on_tick:
                        on_tick()
        except BaseException:
            logging.getLogger("app.media").exception(
                "External tool cancelled/failed: %s", tool,
                extra={"action": "process_interrupted", "stage": "media", "tool_name": tool,
                       "elapsed_ms": round((time.monotonic()-started)*1000, 2),
                       "detail_log": process_log})
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
    if process.returncode:
        logging.getLogger("app.media").error(
            "External tool exited with code %s: %s", process.returncode, tool,
            extra={"action": "process_failed", "stage": "media", "tool_name": tool,
                   "code": process.returncode, "detail_log": process_log,
                   "elapsed_ms": round((time.monotonic()-started)*1000, 2)})
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - 6000))
            error = handle.read().decode("utf-8", "replace")
        raise RuntimeError(f"{Path(argv[0]).name}: {error.strip()}")
    logging.getLogger("app.media").info(
        "External tool completed: %s", tool,
        extra={"action": "process_done", "stage": "media", "tool_name": tool,
               "detail_log": process_log,
               "elapsed_ms": round((time.monotonic()-started)*1000, 2)})
    return output.decode("utf-8", "replace")


def inspect_media(path: Path, workdir: Path, cancelled=lambda: False) -> dict:
    return json.loads(run_command([str(FFPROBE), "-v", "error", "-show_format", "-show_streams",
                                   "-of", "json", str(path.resolve())], workdir, cancelled, 45))


def validate_export(path: Path, expected_duration: float, workdir: Path, cancelled=lambda: False,
                    max_duration: float | None = None, *, full_decode: bool = False) -> dict:
    """Inspect metadata; fresh exports also require an explicit complete decode.

    A caller reusing a previously decoded artifact may omit ``full_decode`` only
    after verifying that its bytes still match that artifact's identity.
    """
    if not path.is_file() or path.stat().st_size < 1000:
        raise ValueError("Недописанный или пустой результат")
    info = inspect_media(path, workdir, cancelled)
    videos = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if len(videos) != 1 or not audios:
        raise ValueError("Результат не содержит видео и звука")
    video, audio = videos[0], audios[0]
    numerator, denominator = map(int, video["avg_frame_rate"].split("/"))
    duration = float(info["format"]["duration"])
    ceiling = max_duration if max_duration is not None else MAX_DURATION
    if (video["codec_name"] != "h264" or audio["codec_name"] != "aac"
            or video["width"] != 1080 or video["height"] != 1920 or denominator == 0
            or abs(numerator / denominator - 30) > 0.01
            or duration > ceiling + .001 or abs(duration - expected_duration) > 0.15):
        raise ValueError("Результат не соответствует формату или длительности шортса")
    audio_duration = float(audio.get("duration", duration))
    video_duration = float(video.get("duration", duration))
    if abs(audio_duration - video_duration) > 0.15:
        raise ValueError("Обнаружено рассогласование длительности видео и звука")
    if full_decode:
        # ffprobe reads the container, not every packet. Fail on decode errors
        # anywhere in the result, before its partial name is published.
        run_render_command([str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-nostdin',
                            '-xerror', '-err_detect', 'explode', '-i', str(path.resolve()),
                            '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                           workdir, duration, cancelled)
    return {"duration": duration, "width": video["width"], "height": video["height"], "codec": "h264",
            'full_decode': full_decode, 'validation_version': EXPORT_VALIDATION_VERSION}


def crop_size(width: int, height: int) -> tuple[int, int]:
    if width / height >= 9 / 16:
        return max(2, int(height * 9 / 16) // 2 * 2), height // 2 * 2
    return width // 2 * 2, max(2, int(width * 16 / 9) // 2 * 2)


def crop_position(x: float, y: float, width: int, height: int) -> tuple[float, float]:
    cw, ch = crop_size(width, height)
    return (min(max(x * width - cw / 2, 0), width - cw),
            min(max(y * height - ch / 2, 0), height - ch))


def _smooth_expression(anchors: list[tuple[float, float]], hard_cuts: set[float] | None = None) -> str:
    # Hold a speaker's composition, then move briefly into the next anchor.
    # Smoothstep has zero endpoint velocity; long dialogue gaps never pan slowly
    # through empty space between the two speakers.
    expression = f"{anchors[-1][1]:.4f}"
    for (t0, p0), (t1, p1) in reversed(list(zip(anchors, anchors[1:]))):
        if hard_cuts and t1 in hard_cuts:
            expression = f"if(lt(t,{t1:.6f}),{p0:.4f},{expression})"
            continue
        if t1 - t0 < 0.001:
            continue
        transition = max(t0, t1 - 0.25)
        fraction = f"clip((t-{transition:.6f})/{t1-transition:.6f},0,1)"
        position = f"{p0:.4f}+({p1-p0:.4f})*({fraction})*({fraction})*(3-2*({fraction}))"
        expression = f"if(lt(t,{t1:.6f}),{position},{expression})"
    return expression


def crop_expressions(cut: dict, width: int, height: int) -> tuple[str, str]:
    # Framing has already resolved uncertainty into a held composition or an
    # explicit fallback. Confidence describes the evidence, not whether a
    # timeline anchor can be discarded (a new-shot centre reset may be zero).
    anchors = cut.get("focus", []) or [{"time": cut["start"], "x": 0.5, "y": 0.5}]
    coordinates = {}
    for anchor in anchors:
        coordinates[round(max(0.0, anchor["time"] - cut["start"]), 6)] = (
            crop_position(anchor["x"], anchor["y"], width, height), anchor.get("hard_cut", False))
    ordered = sorted(coordinates.items())
    if ordered[0][0] > 0:
        ordered.insert(0, (0.0, ordered[0][1]))
    hard_cuts = {t for t, (_, hard_cut) in ordered if hard_cut}
    return tuple(_smooth_expression([(t, p[axis]) for t, (p, _) in ordered], hard_cuts) for axis in (0, 1))


def choose_encoder(workdir: Path, cancelled=lambda: False) -> str:
    try:
        run_command([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                     "color=size=256x256:rate=30", "-frames:v", "1", "-c:v", "h264_nvenc",
                     "-f", "null", "-"], workdir, cancelled, 30)
        return "h264_nvenc"
    except (RuntimeError, TimeoutError):
        return "libx264"


def run_render_command(args, workdir, duration, cancelled, on_progress=None):
    """Watch media advancement, including renders without a UI callback.

    The stall watchdog is separate from a generous workload-based deadline. It
    catches a live but stuck FFmpeg without imposing an episode-wide timer.
    ``run_command`` owns and terminates only the process it started.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Длительность обработки должна быть положительной')
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    progress = workdir / ('progress_' + uuid.uuid4().hex + '.txt')
    args = [*args[:-1], '-progress', str(progress.resolve()), '-nostats', args[-1]]
    inputs = args.count('-i')
    bootstrap = _RENDER_BOOTSTRAP_SECONDS + 2 * inputs
    deadline = bootstrap + max(_RENDER_STALL_SECONDS,
                              duration * _RENDER_SECONDS_PER_OUTPUT_SECOND + 10 * inputs)
    logging.getLogger('app.media').info(
        'FFmpeg progress policy: bootstrap=%ss, stall=%ss, deadline=%ss',
        bootstrap, _RENDER_STALL_SECONDS, deadline,
        extra={'action': 'render_progress_policy', 'stage': 'media',
               'bootstrap_seconds': bootstrap, 'stall_seconds': _RENDER_STALL_SECONDS,
               'timeout_seconds': deadline, 'output_duration': duration, 'input_count': inputs})
    started = advanced_at = time.monotonic()
    maxima = {'out_time_us': 0, 'frame': 0}
    started_output = False
    last = -1.0
    def tick():
        nonlocal last, advanced_at, started_output
        now = time.monotonic()
        values = {}
        try:
            with progress.open('rb') as handle:
                handle.seek(max(0, progress.stat().st_size - 4096))
                lines = handle.read().decode('ascii', 'ignore').splitlines()
            for line in lines:
                key, separator, raw = line.partition('=')
                if separator and key in maxima:
                    try:
                        values[key] = max(values.get(key, 0), int(raw))
                    except ValueError:
                        pass  # A tick may race a partially written progress line.
        except OSError:
            pass
        if any(value > maxima[key] for key, value in values.items()):
            advanced_at = now
            started_output = True
            for key, value in values.items():
                maxima[key] = max(maxima[key], value)
        limit = _RENDER_STALL_SECONDS if started_output else bootstrap
        if now - (advanced_at if started_output else started) > limit:
            raise TimeoutError('FFmpeg не продвигает обработку: ' +
                               ('остановился вывод кадров' if started_output else 'нет первых кадров'))
        value = min(.999, max(0, maxima['out_time_us'] / 1_000_000 / duration))
        if on_progress and value > last:
            last = value
            on_progress(value)
    return run_command(args, workdir, cancelled, timeout=deadline, on_tick=tick)


def render_part(source: Path, part: dict, probe: dict, output_dir: Path, workdir: Path,
                encoder: str, cancelled=lambda: False,
                background_music: dict | None = None, finishing: dict | None = None, *, on_progress=None,
                on_validated=None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    basename = f"part_{part['index']:03}"
    destination = output_dir / (basename + ".mp4")
    partial = workdir / (basename + ".partial.mp4")
    ass_path = workdir / "captions.ass"
    layout = part.get('layout', 'portrait')
    write_ass(ass_path, part["subtitles"], part["index"], part["duration"],
              part.get('caption_style', 'classic'), layout, (finishing or {}).get("subtitles"))
    args = [str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-nostdin", "-y"]
    filters, video_inputs, audio_inputs = [], [], []
    offset = 0.0
    cw, ch = crop_size(probe["width"], probe["height"])
    visual_config = (finishing or {}).get("video", {})
    social = visual_config.get("frame_style") == "social"
    social_box = None
    if social:
        from app.social_frame import write_card
        social_box = write_card(workdir / "social-card.png", probe["width"], probe["height"], visual_config,
                                avatar=(finishing or {}).get('avatar_path'), duration=part['duration'])
    blur_amount = max(0, round(float(visual_config.get("blur", 24)) / 2))
    background_blur = f",boxblur={blur_amount}:2" if blur_amount else ""
    for i, cut in enumerate(part["cuts"]):
        duration = cut["end"] - cut["start"]
        args.extend(["-ss", f"{cut['start']:.6f}", "-t", f"{duration:.6f}", "-i", str(source.resolve())])
        x, y = crop_expressions(cut, probe["width"], probe["height"])
        if layout == 'cinema' or social:
            filters.append(f"[{i}:v:0]trim=duration={duration:.6f},setpts=PTS-STARTPTS,split=2[bg{i}][fg{i}]")
            # Blur at a small resolution, then upscale: inexpensive background
            # while the sharp foreground preserves the entire source image.
            filters.append(f"[bg{i}]scale=270:480:force_original_aspect_ratio=increase,"
                           f"crop=270:480{background_blur},eq=brightness=-0.12:saturation=0.75,"
                           f"scale=1080:1920[back{i}]")
            foreground = (f"scale={social_box['width']}:{social_box['height']}" if social
                          else "scale=1080:1080:force_original_aspect_ratio=decrease:force_divisible_by=2")
            position = f"{social_box['x']}:{social_box['y']}" if social else "(W-w)/2:(H-h)/2"
            filters.append(f"[fg{i}]{foreground},setsar=1[front{i}]")
            filters.append(f"[back{i}][front{i}]overlay={position}:shortest=1,"
                           f"setsar=1,format=yuv420p,setpts=PTS+{offset:.6f}/TB[v{i}]")
        else:
            filters.append(f"[{i}:v:0]trim=duration={duration:.6f},setpts=PTS-STARTPTS,"
                           f"crop={cw}:{ch}:x='{x}':y='{y}',scale=1080:1920:flags=lanczos,"
                           f"setsar=1,format=yuv420p,setpts=PTS+{offset:.6f}/TB[v{i}]")
        filters.append(f"[{i}:a:{probe.get('audio_stream', 0)}]atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,"
                       f"aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{i}]")
        video_inputs.append(f"[v{i}]")
        audio_inputs.append(f"[a{i}]")
        offset += duration
    # Place video on the exact montage clock before applying output FPS. Joint
    # audio/video concat would pad audio to every rounded video-frame duration,
    # accumulating subtitle drift across fractional-frame cuts.
    filters.append("".join(video_inputs) + f"interleave=nb_inputs={len(part['cuts'])}:duration=longest,"
                   f"trim=duration={part['duration']:.6f},fps=30[joined]")
    filters.append("".join(audio_inputs) + f"concat=n={len(part['cuts'])}:v=0:a=1[audio]")
    # The script and ASS names are safe ASCII relative paths, independent of source path characters.
    video_effects = []
    visual = (finishing or {}).get("video", {})
    if visual:
        # Publication mode must keep the whole source, even if the previous
        # plain/crop mode had a stored zoom. The card itself is never cropped.
        zoom = 1.0 if social else float(visual.get("zoom", 100)) / 100
        if zoom < 1:
            # Scaling below 100% creates an image smaller than 1080x1920.
            # Cropping that smaller image fails in FFmpeg; pad the zoomed-out
            # frame to the target canvas instead (matching the editor preview).
            video_effects.append(f"scale=iw*{zoom:.4f}:ih*{zoom:.4f}:flags=lanczos,"
                                 "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black")
        elif zoom > 1:
            video_effects.append(f"scale=iw*{zoom:.4f}:ih*{zoom:.4f}:flags=lanczos,"
                                 "crop=1080:1920:(in_w-out_w)/2:(in_h-out_h)/2")
        brightness = (float(visual.get("brightness", 100)) - 100) / 250
        if brightness:
            video_effects.append(f"eq=brightness={brightness:.4f}")
        vignette = float(visual.get("vignette", 0))
        if vignette:
            video_effects.append(f"vignette=angle=PI/{max(3.0, 28.0 - vignette / 2):.3f}")
    base_label = "joined"
    if video_effects:
        filters.append("[joined]" + ",".join(video_effects) + "[graded]")
        base_label = "graded"
    if social:
        args.extend(["-loop", "1", "-i", str((workdir / "social-card.png").resolve())])
        filters.append(f"[{base_label}][{len(part['cuts'])}:v:0]overlay=0:0:shortest=1[carded]")
        base_label = "carded"
    filters.append(f"[{base_label}]ass=filename=captions.ass[video]")
    audio_label = "[audio]"
    if background_music:
        music_path = background_music["path"]
        volume = float(background_music.get("volume", 0.15))
        duck_volume = float(background_music.get("volume_music_duck", 0.015))
        duck_intervals = background_music.get("duck_intervals", [])
        fade_in = bool(background_music.get("fade_in", True))
        fade_out = bool(background_music.get("fade_out", True))
        music_index = len(part["cuts"]) + int(social)
        args.extend(["-stream_loop", "-1", "-i", str(music_path.resolve())])
        fade_in_duration = min(float(background_music.get("fade_in_seconds", 1.0)), part["duration"] / 2.0)
        fade_out_duration = min(float(background_music.get("fade_out_seconds", 1.0)), part["duration"] / 2.0)
        from .audio_analysis import build_volume_expression
        vol_expr = build_volume_expression(duck_intervals, volume, duck_volume)
        chain = (f"[{music_index}:a:0]atrim=duration={part['duration']:.6f},asetpts=PTS-STARTPTS,"
                 f"aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                 f"volume='{vol_expr}'" if ':eval=frame' in vol_expr else
                 f"[{music_index}:a:0]atrim=duration={part['duration']:.6f},asetpts=PTS-STARTPTS,"
                 f"aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                 f"volume={vol_expr}")
        if fade_in:
            chain += f",afade=t=in:st=0:d={fade_in_duration:.6f}"
        if fade_out:
            chain += f",afade=t=out:st={max(0.0, part['duration'] - fade_out_duration):.6f}:d={fade_out_duration:.6f}"
        chain += "[music]"
        filters.append(chain)
        filters.append("[audio][music]amix=inputs=2:duration=first:normalize=0[mix]")
        filters.append("[mix]alimiter=level=false:limit=0.95[mixed]")
        audio_label = "[mixed]"
    (workdir / "render.ffscript").write_text(";\n".join(filters), encoding="utf-8")
    args.extend(["-filter_complex_script", "render.ffscript", "-filter_complex_threads", "2",
                 "-map", "[video]", "-map", audio_label, "-t", f"{part['duration']:.6f}", "-c:v", encoder])
    if encoder == "h264_nvenc":
        args.extend(["-preset", "p4", "-cq", "20", "-b:v", "0"])
    else:
        args.extend(["-preset", "medium", "-crf", "20", "-threads", "4"])
    args.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                 "-max_muxing_queue_size", "4096", str(partial.resolve())])
    try:
        run_render_command(args, workdir, part['duration'], cancelled, on_progress)
    except RuntimeError:
        if encoder != "h264_nvenc":
            raise
        return render_part(source, part, probe, output_dir, workdir, "libx264", cancelled,
                           background_music=background_music, finishing=finishing, on_progress=on_progress,
                           on_validated=on_validated)
    validate_export(partial, part["duration"], workdir, cancelled,
                    max_duration=150.0 if part.get("duration", 0) > MAX_DURATION else None,
                    full_decode=True)
    if cancelled():
        raise InterruptedError("Обработка отменена")
    # The requested hardware encoder can fall back per part. Record the actual
    # successful encoder without changing the public Path return contract.
    metadata = workdir / "render-info.json"
    temporary = metadata.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"encoder": encoder}), encoding="utf-8")
    _safe_replace(temporary, metadata)
    # Sidecars are written before the MP4 is published as the commit marker.
    srt_partial = workdir / (basename + ".srt")
    write_srt(srt_partial, part["subtitles"])
    _safe_replace(srt_partial, output_dir / (basename + ".srt"))
    _safe_replace(ass_path, output_dir / (basename + ".ass"))
    _safe_replace(partial, destination)
    if on_validated is not None:
        from .content_identity import file_sha256
        on_validated({'full_decode_version': EXPORT_VALIDATION_VERSION,
                      'video_sha256': file_sha256(destination, cancelled),
                      'subtitles_sha256': file_sha256(destination.with_suffix('.srt'), cancelled)})
    return destination


def _safe_replace(src: Path, dst: Path, retries: int = 8, delay: float = 0.5) -> None:
    """Atomic replace with retries to gracefully handle transient Windows file locks."""
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
