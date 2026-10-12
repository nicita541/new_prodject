"""Bounded local comparisons of focus prompts; never modifies production checkpoints."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from app.vision import LocalVision
from app.config import JOBS, ROOT, STORY_MODEL, STORY_PROJECTOR, VLM_MODEL, VLM_PROJECTOR
from app.framing import FOCUS_SCHEMA, _FrameReader, _grid_image, focus_samples, temporal_times


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(picture, path):
    success, encoded = cv2.imencode(".jpg", picture, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success:
        raise ValueError("JPEG encoding failed")
    path.write_bytes(encoded.tobytes())


def labelled(picture):
    resized = cv2.resize(picture, (960, 540), interpolation=cv2.INTER_AREA)
    canvas = np.full((600, 960, 3), 245, np.uint8)
    canvas[60:] = resized
    for i in range(11):
        x = min(959, round(i * 96))
        cv2.line(canvas, (x, 48), (x, 599), (80, 220, 240), 1)
        cv2.putText(canvas, f"{i / 10:.1f}", (max(0, min(908, x - 23)), 34), cv2.FONT_HERSHEY_SIMPLEX, .65, (15, 15, 15), 2, cv2.LINE_AA)
    return canvas


def candidates(picture):
    centers = [i / 10 for i in range(2, 9)]
    source = cv2.resize(picture, (960, 540), interpolation=cv2.INTER_AREA)
    canvas = np.full((900, 1120, 3), 25, np.uint8)
    canvas[:540, 80:1040] = source
    height, width = picture.shape[:2]
    crop_width = min(width, round(height * 9 / 16))
    for i, center in enumerate(centers):
        left = max(0, min(width - crop_width, round(width * center - crop_width / 2)))
        crop = cv2.resize(picture[:, left:left + crop_width], (152, 270), interpolation=cv2.INTER_AREA)
        offset = i * 160
        canvas[590:860, offset:offset + 152] = crop
        cv2.putText(canvas, chr(65 + i), (offset + 64, 575), cv2.FONT_HERSHEY_SIMPLEX, .9, (240, 240, 240), 2, cv2.LINE_AA)
    return canvas, {chr(65 + i): center for i, center in enumerate(centers)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=uuid.UUID)
    parser.add_argument("--anchors", nargs="*", type=float, default=[])
    parser.add_argument("--extra-times", nargs="*", type=float, default=[])
    parser.add_argument("--model", choices=("4b", "9b"), default="9b")
    parser.add_argument("--modes", nargs="+", choices=("existing", "action", "single", "source960", "labelled", "candidates"), default=["existing", "source960", "labelled", "candidates"])
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    job = JOBS / str(args.job)
    directory = job / "diagnostics" / ("framing-" + args.model + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    source = Path(read(job / "source.json")["path"]).resolve()
    source.relative_to(ROOT)
    probe = read(job / "probe.json")
    transcript, shots = read(job / "transcript.json"), read(job / "shots.json")
    # Compare the frames for the already-rendered plan. A newer story refinement
    # may have changed events.json while the old focus checkpoints still exist.
    events = read(job / "plan.json")["events"]
    located = []
    for event in events:
        stem = hashlib.sha256(str(event["id"]).encode()).hexdigest()[:24]
        checkpoint = job / "focus" / (stem + ".json")
        if not checkpoint.is_file():
            continue
        saved = read(checkpoint)
        samples = focus_samples(event, transcript, shots)
        if saved.get("version", 0) < 6:
            samples = [sample for sample in samples if not sample.get("periodic")]
        for i, anchor in enumerate(saved["focus"]):
            if any(abs(anchor["time"] - target) < .035 for target in args.anchors):
                if i >= len(samples) or abs(samples[i]["time"] - anchor["time"]) > .002:
                    raise ValueError("Saved focus does not match current transcript/plan samples")
                sample = samples[i]
                if not sample["phrase"]:
                    spoken = next((segment for segment in transcript.get("segments", [])
                                   if segment["start"] <= sample["sample_time"] < segment["end"]), None)
                    if spoken:
                        sample["phrase"] = str(spoken.get("text", ""))[:180]
                located.append({"event": event, "anchor": anchor, "sample": sample,
                                "times": temporal_times(sample, event, shots),
                                "image": job / "focus" / (stem + f"_{i:03}.jpg")})
    if len(located) != len(args.anchors):
        raise ValueError(f"Expected {len(args.anchors)} anchors, found {len(located)}")
    for timestamp in args.extra_times:
        event = next((event for event in events if event["start"] <= timestamp < event["end"]), None)
        if event is None:
            raise ValueError("Extra timestamp is outside the saved plan events")
        sample = {"time": timestamp, "sample_time": timestamp, "phrase": ""}
        located.append({"event": event, "anchor": {"time": timestamp}, "sample": sample,
                        "times": temporal_times(sample, event, shots), "image": None})
    reader = _FrameReader(source, probe, lambda: False)
    cases = []
    try:
        for entry in sorted(located, key=lambda entry: entry["anchor"]["time"]):
            timestamp = entry["times"][0]
            name = str(entry["anchor"]["time"]).replace(".", "_")
            picture = reader.frame(timestamp)
            if entry["image"] is None:
                entry["image"] = directory / (name + "_temporal.jpg")
                _grid_image([reader.frame(time) for time in entry["times"]], entry["times"], entry["image"])
            image = cv2.imdecode(np.frombuffer(entry["image"].read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            paths = {"existing": entry["image"], "action": entry["image"]}
            single = directory / (name + "_single.jpg"); save(image[:270], single); paths["single"] = single
            larger = directory / (name + "_source960.jpg"); save(cv2.resize(picture, (960, 540)), larger); paths["source960"] = larger
            grid = directory / (name + "_labelled.jpg"); save(labelled(picture), grid); paths["labelled"] = grid
            strip, centers = candidates(picture)
            candidate_path = directory / (name + "_candidates.jpg"); save(strip, candidate_path); paths["candidates"] = candidate_path
            entry.update(paths=paths, candidate_centers=centers)
            cases.append(entry)
    finally:
        reader.close()
    print(str(directory), flush=True)
    model, projector = (STORY_MODEL, STORY_PROJECTOR) if args.model == "9b" else (VLM_MODEL, VLM_PROJECTOR)
    results = []
    with LocalVision(directory, lambda: False, model=model, projector=projector, thinking=args.thinking) as vision:
        for case in cases:
            phrase = case["sample"]["phrase"]
            for mode in args.modes:
                for repeat in range(args.repeat):
                    schema, limit = FOCUS_SCHEMA, 160
                    if mode == "action":
                        prompt = ('Three consecutive frames TOP to BOTTOM. There is no recognized speech for this sample. '
                                  'Locate the horizontal center of the MAIN VISIBLE ACTION, gesture or object interaction, '
                                  'not automatically a face. Include the meaningful interaction and reacting character when feasible. '
                                  'If no action is visible, locate the main visible person or meaningful scene. '
                                  'x,y are normalized 0..1 WITHIN ONE PANEL, not the full strip. '
                                  'Set visible_speaker=false; an open mouth alone does not prove speaking. '
                                  'Return JSON matching the coordinate schema.')
                    elif mode == "existing":
                        prompt = ('Three consecutive frames TOP to BOTTOM. Compare mouth motion and locate the visible speaker face center, '
                                  'otherwise the main visible person/action. x,y are normalized 0..1 WITHIN ONE PANEL, not the full strip. '
                                  'visible_speaker is true only when mouth motion supports speaking. '
                                  f'Current phrase (evidence): {json.dumps(phrase, ensure_ascii=False)}. '
                                  'Return JSON matching the coordinate schema.')
                    elif mode == "candidates":
                        schema = {"type": "object", "properties": {"candidate": {"type": "string", "enum": list(case["candidate_centers"])}, "confidence": {"type": "number"}, "subject": {"type": "string"}}, "required": ["candidate", "confidence", "subject"], "additionalProperties": False}
                        prompt = ('TOP image is the current complete source frame. Below are seven portrait crop candidates A to G of that SAME frame. '
                                  'Choose the ONE crop containing the ENTIRE face and hair of the visible speaking/main character, with face closest to the crop horizontal center. '
                                  'Do not select a listener seen from behind or empty background. Determine identity from the source image, not from past or future. '
                                  f'Current phrase: {json.dumps(phrase, ensure_ascii=False)}. '
                                  'Return candidate letter, confidence and a brief visual subject description.')
                        limit = 220
                    else:
                        prompt = ('This is ONE CURRENT source frame; no prior or future frames are shown. '
                                  'Locate the center of the ENTIRE FACE of the front-facing visible speaking/main character, NOT their body or the image center. '
                                  'x=0 at source left edge, x=1 at source right edge. y=0 at source top edge, y=1 at source bottom edge. '
                                  + ('The wide ruler ABOVE the picture gives the horizontal x coordinates. Use the two nearest labelled grid lines bracketing the face and their midpoint. Ignore the ruler for y. ' if mode == "labelled" else '')
                                  + f'Current phrase: {json.dumps(phrase, ensure_ascii=False)}. '
                                  + 'Return JSON matching the coordinate schema. visible_speaker=true only if the visible mouth is open as speaking.')
                    started = time.monotonic()
                    try:
                        answer = vision.query(prompt, case["paths"][mode], max_tokens=limit, schema=schema)
                        if mode == "candidates":
                            answer["x"] = case["candidate_centers"].get(answer.get("candidate"))
                        result = {"anchor": case["anchor"], "time": case["times"][0], "phrase": phrase,
                                  "image": str(case["paths"][mode].relative_to(ROOT)),
                                  "mode": mode, "repeat": repeat, "answer": answer}
                    except Exception as error:
                        result = {"anchor": case["anchor"], "time": case["times"][0], "mode": mode, "repeat": repeat, "error": str(error)}
                    result["seconds"] = round(time.monotonic() - started, 2)
                    results.append(result)
                    (directory / "results.json").write_text(json.dumps({"model": args.model, "thinking": args.thinking, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
