"""Shot/reply-level portrait focus inferred from individual local video frames."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.error

from .config import VLM_MODEL, VLM_PROJECTOR

FOCUS_VERSION = 6
MIN_CONFIDENCE = 0.55
MAX_SAMPLE_INTERVAL = 4.0
NORMALIZED_VALUES = [index / 20 for index in range(21)]
FOCUS_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number", "enum": NORMALIZED_VALUES},
        "y": {"type": "number", "enum": NORMALIZED_VALUES},
        "confidence": {"type": "number", "enum": NORMALIZED_VALUES},
        "visible_speaker": {"type": "boolean"},
    },
    "required": ["x", "y", "confidence", "visible_speaker"],
    "additionalProperties": False,
}


def _retained_ids(events: list[dict]) -> set[str]:
    indexed = {event["id"]: event for event in events}
    retained = {event["id"] for event in events if (event["kind"] == "story" and event["importance"] >= 3)
                or event["importance"] >= 4}
    if not retained:
        retained = {event["id"] for event in events if event["kind"] == "story"}
    pending = list(retained)
    while pending:
        for dependency in indexed[pending.pop()].get("requires", []):
            if dependency not in indexed:
                raise ValueError("Неизвестная причинная связь при кадрировании")
            if dependency not in retained:
                retained.add(dependency)
                pending.append(dependency)
    return retained


def _shot_at(time: float, shots: list[dict]) -> dict | None:
    return next((shot for shot in shots if shot["start"] <= time < shot["end"]), None)


def focus_samples(event: dict, transcript: dict, shots: list[dict]) -> list[dict]:
    """Anchor at a real boundary, inspect mouth evidence just inside the shot/reply."""
    samples = []
    for selection in event.get("selected_ranges") or [event]:
        left, right = max(event["start"], selection["start"]), min(event["end"], selection["end"])
        if right <= left:
            continue
        for shot in shots:
            start, end = max(left, shot["start"]), min(right, shot["end"])
            if start >= end:
                continue
            samples.append({"time": start, "sample_time": min(start + 0.25, (start + end) / 2),
                            "shot_id": shot["id"], "phrase": "", "reply": False})
        for segment in transcript.get("segments", []):
            start, end = max(left, segment["start"]), min(right, segment["end"])
            if start >= end:
                continue
            words = [word for word in transcript.get("words", [])
                     if word["start"] < end and word["end"] > start]
            if words:
                word = words[0]
                sample_time = (max(start, word["start"]) + min(end, word["end"])) / 2
            else:
                sample_time = min(start + 0.25, (start + end) / 2)
            shot = _shot_at(sample_time, shots)
            # A reply can begin off-screen and cross a shot change before its
            # first word midpoint. Never apply a new face to the preceding shot.
            anchor_time = max(start, shot["start"]) if shot else start
            samples.append({"time": anchor_time, "sample_time": sample_time,
                            "shot_id": shot["id"] if shot else None,
                            "phrase": str(segment.get("text", ""))[:180], "reply": True})
        if not any(left <= sample["time"] < right for sample in samples):
            samples.append({"time": left, "sample_time": min(left + 0.25, (left + right) / 2),
                            "shot_id": None, "phrase": "", "reply": False})
    deduplicated = []
    for sample in sorted(samples, key=lambda item: (item["time"], not item["reply"])):
        if (deduplicated and sample["shot_id"] == deduplicated[-1]["shot_id"]
                and abs(sample["sample_time"] - deduplicated[-1]["sample_time"]) < 1.0):
            if sample["reply"] and not deduplicated[-1]["reply"]:
                deduplicated[-1] = sample
            continue
        deduplicated.append(sample)
    # Shot detection is approximate and a long shot can contain camera or
    # character movement. Refresh geometry within retained material, without
    # pretending these observations are actual cuts or replacing real replies.
    periodic = []
    for selection in event.get("selected_ranges") or [event]:
        for shot in shots:
            left = max(event["start"], selection["start"], shot["start"])
            right = min(event["end"], selection["end"], shot["end"])
            if right <= left:
                continue
            boundaries = sorted({left, right, *(sample["time"] for sample in deduplicated
                                                if sample["shot_id"] == shot["id"]
                                                and left <= sample["time"] < right)})
            for start, end in zip(boundaries, boundaries[1:]):
                gap = end - start
                if gap <= MAX_SAMPLE_INTERVAL + 1e-6:
                    continue
                additions = math.ceil(gap / MAX_SAMPLE_INTERVAL) - 1
                for index in range(1, additions + 1):
                    timestamp = round(start + gap * index / (additions + 1), 6)
                    periodic.append({"time": timestamp,
                                     "sample_time": min(timestamp + 0.25, (timestamp + right) / 2),
                                     "shot_id": shot["id"], "phrase": "", "reply": False, "periodic": True})
    return sorted(deduplicated + periodic, key=lambda sample: sample["time"])


def _focus_prompt(sample: dict) -> str:
    if not sample["phrase"]:
        return ('Three consecutive frames TOP to BOTTOM. There is no recognized speech for this sample. '
                'Locate the horizontal center of the MAIN VISIBLE ACTION, gesture or object interaction, '
                'not automatically a face. Include the meaningful interaction and reacting character when feasible. '
                'If no action is visible, locate the main visible person or meaningful scene. '
                'x,y are normalized 0..1 WITHIN ONE PANEL, not the full strip. '
                'Set visible_speaker=false; an open mouth alone does not prove speaking. '
                'Return JSON matching the coordinate schema.')
    return ('Three consecutive frames TOP to BOTTOM. Compare mouth motion and locate the visible speaker face center, '
            'otherwise the main visible person/action. x,y are normalized 0..1 WITHIN ONE PANEL, not the full strip. '
            'visible_speaker is true only when mouth motion supports speaking. '
            f'Current phrase (evidence): {json.dumps(sample["phrase"], ensure_ascii=False)}. '
            'Return JSON matching the coordinate schema.')


def temporal_times(sample: dict, event: dict, shots: list[dict]) -> list[float]:
    """Three consecutive observations confined to one actual shot and cut."""
    timestamp = sample["sample_time"]
    selection = next((interval for interval in event.get("selected_ranges") or [event]
                      if interval["start"] <= timestamp < interval["end"]), event)
    left, right = max(event["start"], selection["start"]), min(event["end"], selection["end"])
    shot = _shot_at(timestamp, shots)
    if shot:
        left, right = max(left, shot["start"]), min(right, shot["end"])
    available = max(0.0, right - left - 0.001)
    factor = min(1.0, available / 0.25)
    base = max(left, min(timestamp, right - 0.001 - 0.25 * factor))
    return [round(base + delta * factor, 6) for delta in (0, 0.12, 0.25)]


class _FrameReader:
    def __init__(self, source: Path, probe: dict, cancelled):
        import cv2
        self.cv2 = cv2
        self.cancelled = cancelled
        self.capture = cv2.VideoCapture(str(source.resolve()))
        if not self.capture.isOpened():
            self.capture.release()
            raise ValueError("Не удалось открыть серию для кадрирования")
        self.fps = float(probe.get("fps") or self.capture.get(cv2.CAP_PROP_FPS) or 30)
        if not math.isfinite(self.fps) or self.fps <= 0:
            self.fps = 30
        count = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
        self.frame_count = int(count) if math.isfinite(count) and count > 0 else None

    def frame(self, timestamp: float):
        target = max(0, int(timestamp * self.fps))
        if self.frame_count:
            # Container duration can include a few audio-only tail samples.
            target = min(target, self.frame_count - 1)
        current = int(self.capture.get(self.cv2.CAP_PROP_POS_FRAMES))
        if target < current or target - current > self.fps:
            if not self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, target):
                raise ValueError("Не удалось перейти к кадру серии")
            current = int(self.capture.get(self.cv2.CAP_PROP_POS_FRAMES))
        picture = None
        while current <= target:
            if self.cancelled():
                raise InterruptedError("Обработка отменена")
            success, picture = self.capture.read()
            if not success:
                raise ValueError("Не удалось прочитать кадр серии")
            current += 1
        if picture is None:
            raise ValueError("Кадр серии отсутствует")
        return picture

    def close(self):
        self.capture.release()


def _grid_picture(picture):
    import cv2
    resized = cv2.resize(picture, (480, 270), interpolation=cv2.INTER_AREA)
    overlay = resized.copy()
    for index in range(1, 10):
        x, y = int(index * 48), int(index * 27)
        cv2.line(overlay, (x, 0), (x, 269), (190, 190, 190), 1)
        cv2.line(overlay, (0, y), (479, y), (190, 190, 190), 1)
    resized = cv2.addWeighted(resized, 0.85, overlay, 0.15, 0)
    for index in range(1, 10):
        x, y = int(index * 48), int(index * 27)
        for text, position in [(f"x=.{index}", (x - 12, 264)), (f"y=.{index}", (2, y + 3))]:
            cv2.putText(resized, text, position, cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(resized, text, position, cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1, cv2.LINE_AA)
    return resized


def _grid_image(pictures: list, times: list[float], path: Path) -> None:
    import cv2
    panels = []
    for index, (picture, timestamp) in enumerate(zip(pictures, times), 1):
        panel = _grid_picture(picture)
        text = f"Frame {index} | {timestamp:.3f}s | x,y within this panel"
        cv2.putText(panel, text, (7, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(panel, text, (7, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1, cv2.LINE_AA)
        panels.append(panel)
    encoded, buffer = cv2.imencode(".jpg", cv2.vconcat(panels), [cv2.IMWRITE_JPEG_QUALITY, 87])
    if not encoded:
        raise ValueError("Не удалось подготовить кадр для модели")
    # imwrite has inconsistent Unicode filename support across Windows builds.
    path.write_bytes(buffer.tobytes())


def _single_image(picture, path: Path) -> None:
    import cv2
    encoded, buffer = cv2.imencode(".jpg", _grid_picture(picture), [cv2.IMWRITE_JPEG_QUALITY, 87])
    if not encoded:
        raise ValueError("Не удалось подготовить текущий кадр")
    path.write_bytes(buffer.tobytes())


def _coordinates(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Модель не вернула координаты персонажа")
    values = {}
    for key in ("x", "y", "confidence"):
        value = raw.get(key, 0.5 if key == "y" else None)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Некорректные координаты персонажа")
        if not 0 <= value <= 1:
            raise ValueError("Координаты персонажа должны быть нормализованы в диапазоне 0..1")
        values[key] = float(value)
    return values


def _valid_checkpoint(data: dict, signature: str, event: dict) -> bool:
    try:
        if (not isinstance(data, dict) or data.get("version") != FOCUS_VERSION or data.get("signature") != signature
                or not data.get("focus") or not isinstance(data.get("warnings"), list)):
            return False
        subject = data.get("previous_subject")
        if subject is not None:
            coordinates = _coordinates(subject)
            if any(coordinates[key] != subject[key] for key in coordinates):
                return False
        if "previous_shot_id" not in data or "previous_selection" not in data:
            return False
        if data["previous_shot_id"] is not None and not isinstance(data["previous_shot_id"], str):
            return False
        selection = data["previous_selection"]
        if selection is not None and (not isinstance(selection, list) or len(selection) != 2
                                      or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in selection)
                                      or selection[0] >= selection[1]):
            return False
        previous = event["start"]
        for anchor in data["focus"]:
            coordinates = _coordinates(anchor)
            if any(coordinates[key] != anchor[key] for key in coordinates):
                return False
            time = float(anchor["time"])
            if not math.isfinite(time) or not previous <= time <= event["end"]:
                return False
            previous = time
        return all(isinstance(warning, str) for warning in data["warnings"])
    except (KeyError, TypeError, ValueError):
        return False


def refine_focus(source: Path, probe: dict, transcript: dict, shots: list, events: list, job_dir: Path,
                 vision, report, cancelled) -> list[dict]:
    """Return refined copies; cached checkpoints require the exact input signature."""
    source_stat = source.stat()
    meta_path = job_dir / "analysis.meta.json"
    if meta_path.is_file():
        identity = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        with source.open("rb") as stream:
            identity = {"source": hashlib.file_digest(stream, "sha256").hexdigest()}
    model_stats = []
    for model in (getattr(vision, "model", None) or VLM_MODEL,
                  getattr(vision, "projector", None) or VLM_PROJECTOR):
        model = Path(model)
        model_stats.append({"path": str(model.resolve()), "name": model.name, "size": model.stat().st_size,
                            "mtime_ns": model.stat().st_mtime_ns} if model.is_file()
                           else {"path": str(model.resolve()), "name": model.name})
    settings = {"version": FOCUS_VERSION, "frame_size": [480, 270], "temporal_offsets": [0, 0.12, 0.25],
                "minimum_confidence": MIN_CONFIDENCE,
                "minimum_sample_gap": 1.0, "maximum_sample_interval": MAX_SAMPLE_INTERVAL,
                "source_identity": identity, "model": model_stats,
                "model_profile": {"thinking": bool(getattr(vision, "thinking", False)),
                                  "gpu_layers": getattr(vision, "gpu_layers", 99),
                                  "cpu_projector": bool(getattr(vision, "cpu_projector", False))},
                "source_size": source_stat.st_size, "source_mtime_ns": source_stat.st_mtime_ns,
                "probe": {key: probe.get(key) for key in ("fps", "width", "height", "duration")}}
    if getattr(vision, 'cache_profile', None) is not None:
        settings['provider_profile'] = vision.cache_profile
    focus_dir = job_dir / "focus"
    focus_dir.mkdir(parents=True, exist_ok=True)
    result = copy.deepcopy(events)
    retained = _retained_ids(result)
    relevant = [event for event in result if event["id"] in retained]
    previous_subject = None
    previous_shot_id = None
    previous_selection = None
    reader = None
    try:
        for position, event in enumerate(relevant):
            if cancelled():
                raise InterruptedError("Обработка отменена")
            samples = focus_samples(event, transcript, shots)
            for sample in samples:
                sample["temporal_times"] = temporal_times(sample, event, shots)
                interval = next((selection for selection in event.get("selected_ranges") or [event]
                                 if selection["start"] <= sample["sample_time"] < selection["end"]), event)
                sample["selection_id"] = [max(event["start"], interval["start"]), min(event["end"], interval["end"])]
                if not sample["phrase"]:
                    spoken = next((segment for segment in transcript.get("segments", [])
                                   if segment["start"] <= sample["sample_time"] < segment["end"]), None)
                    if spoken:
                        sample["phrase"] = str(spoken.get("text", ""))[:180]
            inputs = {"settings": settings, "event": {key: value for key, value in event.items()
                                                       if key not in {"focus", "focus_warnings"}},
                      "samples": samples, "previous_subject": previous_subject,
                      "previous_shot_id": previous_shot_id, "previous_selection": previous_selection}
            signature = hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            # Never trust model-provided IDs as paths.
            checkpoint = focus_dir / (hashlib.sha256(str(event["id"]).encode("utf-8")).hexdigest()[:24] + ".json")
            cached = None
            if checkpoint.is_file():
                try:
                    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                    if _valid_checkpoint(saved, signature, event):
                        cached = saved
                except (ValueError, TypeError):
                    pass
            report("framing", 0.51 + 0.14 * position / max(1, len(relevant)),
                   f"Кадрирование: сцена {position + 1} из {len(relevant)}")
            if cached is not None:
                event["focus"], event["focus_warnings"] = cached["focus"], cached["warnings"]
                previous_subject = cached.get("previous_subject")
                previous_shot_id = cached.get("previous_shot_id")
                previous_selection = cached.get("previous_selection")
                continue
            anchors, warnings = [], []
            if reader is None:
                reader = _FrameReader(source, probe, cancelled)
            for index, sample in enumerate(samples):
                if cancelled():
                    raise InterruptedError("Обработка отменена")
                frame = focus_dir / (checkpoint.stem + f"_{index:03}.jpg")
                times = sample["temporal_times"]
                pictures = [reader.frame(timestamp) for timestamp in times]
                _grid_image(pictures, times, frame)
                prompt = _focus_prompt(sample)
                reason = None
                try:
                    raw = vision.query(prompt, frame, max_tokens=120, schema=FOCUS_SCHEMA)
                    coordinates = _coordinates(raw)
                    if sample["phrase"] and raw.get("visible_speaker") is not True:
                        coordinates["confidence"] = min(coordinates["confidence"], 0.5)
                    if coordinates["confidence"] < MIN_CONFIDENCE:
                        reason = "Модель не уверена в видимом говорящем"
                except (ValueError, KeyError, TypeError, RuntimeError, TimeoutError, urllib.error.URLError) as error:
                    coordinates = {"x": 0.5, "y": 0.5, "confidence": 0.0}
                    reason = f"Не удалось определить говорящего: {str(error)[:180]}"
                if reason:
                    same_context = (previous_subject is not None and sample["shot_id"] is not None
                                    and previous_shot_id == sample["shot_id"]
                                    and previous_selection == sample["selection_id"])
                    if same_context:
                        coordinates = {**previous_subject, "held": True}
                        fallback_description = "удержан предыдущий уверенный фокус текущего плана"
                    else:
                        coordinates = {"x": 0.5, "y": 0.5, "confidence": 0.0}
                        previous_subject = None
                        previous_shot_id, previous_selection = sample["shot_id"], sample["selection_id"]
                        fallback_description = "использован центральный фокус"
                        current_frame = frame.with_name(frame.stem + "_main.jpg")
                        _single_image(pictures[0], current_frame)
                        try:
                            if cancelled():
                                raise InterruptedError("Обработка отменена")
                            fallback = _coordinates(vision.query(
                                'Locate the MAIN VISIBLE ACTION, gesture or object interaction center in this CURRENT single frame, '
                                'rather than automatically a face. If no action is visible, use the main visible person or meaningful scene. '
                                'x,y normalized 0..1. Set visible_speaker=false. Return coordinate schema.',
                                current_frame, max_tokens=120, schema=FOCUS_SCHEMA))
                            if fallback["confidence"] >= MIN_CONFIDENCE:
                                coordinates = {**fallback, "main_fallback": True}
                                previous_subject = dict(fallback)
                                fallback_description = "фокус подтверждён по главному видимому участнику или действию текущего кадра"
                        except (ValueError, KeyError, TypeError, RuntimeError, TimeoutError, urllib.error.URLError):
                            pass
                    warnings.append(f"{sample['time']:.3f} с: {reason}; {fallback_description}")
                else:
                    previous_subject = dict(coordinates)
                    previous_shot_id, previous_selection = sample["shot_id"], sample["selection_id"]
                anchors.append({"time": round(sample["time"], 6), **coordinates})
            if not anchors:
                anchors = [{"time": event["start"], **(previous_subject or {"x": 0.5, "y": 0.5, "confidence": 0.0})}]
                warnings.append("В событии не удалось выбрать кадры для определения говорящего")
            event["focus"], event["focus_warnings"] = anchors, warnings
            saved = {"signature": signature, "version": FOCUS_VERSION, "focus": anchors,
                     "warnings": warnings, "previous_subject": previous_subject,
                     "previous_shot_id": previous_shot_id, "previous_selection": previous_selection}
            temporary = checkpoint.with_suffix(".tmp")
            temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, checkpoint)
    finally:
        if reader:
            reader.close()
    return result
