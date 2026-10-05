"""Deterministic, provenance-preserving timeline construction."""
from __future__ import annotations

import math
from .subtitles import make_cues, remap_words

MAX_DURATION = 120.0
TARGET_DURATION = 90.0
PLANNER_VERSION = 11
SCHEMA_VERSION = 1
SPEECH_TAIL = 0.55
SPEECH_LEAD = 0.18


def _number(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Некорректный таймкод")
    return number


def validate_analysis(analysis: dict) -> None:
    duration = _number(analysis["probe"]["duration"])
    if duration <= 0:
        raise ValueError("Пустое видео")
    if not analysis["probe"].get("has_audio"):
        raise ValueError("В серии отсутствует аудиодорожка")
    if int(analysis["probe"]["width"]) < 2 or int(analysis["probe"]["height"]) < 2:
        raise ValueError("Некорректный размер видео")
    events = analysis["events"]
    if not events:
        raise ValueError("Анализ не содержит событий")
    seen, previous = set(), 0.0
    for event in events:
        start, end = _number(event["start"]), _number(event["end"])
        if not (0 <= start < end <= duration + 0.002) or start < previous - 0.002:
            raise ValueError("События пересекаются или выходят за длительность серии")
        if not isinstance(event["id"], str) or event["id"] in seen:
            raise ValueError("Идентификаторы событий должны быть уникальны")
        if event["kind"] not in {"story", "opening", "ending", "recap", "filler"}:
            raise ValueError("Неизвестный тип события")
        if not 1 <= _number(event["importance"]) <= 5:
            raise ValueError("Некорректная важность события")
        if any(dep not in seen for dep in event.get("requires", [])):
            raise ValueError("Событие ссылается на неизвестное или последующее событие")
        for anchor in event.get("focus", []):
            if not start - 0.002 <= _number(anchor["time"]) <= end + 0.002:
                raise ValueError("Кадрирование находится вне события")
            if any(not 0 <= _number(anchor[key]) <= 1 for key in ("x", "y", "confidence")):
                raise ValueError("Некорректная координата кадрирования")
        for boundary in event.get("boundary_times", []):
            if not start <= _number(boundary) <= end:
                raise ValueError("Граница находится вне события")
        for ending in event.get('part_endings', []):
            if (not start < _number(ending['time']) <= end
                    or ending.get('kind') not in ('closure', 'cliffhanger', 'transition')
                    or not isinstance(ending.get('evidence'), str) or not ending['evidence'].strip()
                    or isinstance(ending.get('confidence'), bool) or not .85 <= _number(ending['confidence']) <= 1):
                raise ValueError('Некорректное подтверждение концовки')
        range_end = start
        for selection in event.get("selected_ranges", []):
            left, right = _number(selection["start"]), _number(selection["end"])
            if not start <= left < right <= end or left < range_end:
                raise ValueError("Выбранные исходные фрагменты пересекаются или выходят за событие")
            range_end = right
        for key in ('excluded_title_units', 'excluded_credit_ranges', 'excluded_closing_ranges', 'excluded_review_ranges'):
            for excluded in event.get(key, []):
                if not start <= _number(excluded['start']) < _number(excluded['end']) <= end:
                    raise ValueError('Подтверждённый исключённый фрагмент выходит за событие')
        seen.add(event["id"])
        previous = end
    for key in ("words", "segments"):
        previous_start = -1.0
        for item in analysis["transcript"].get(key, []):
            start, end = _number(item["start"]), _number(item["end"])
            if not 0 <= start < end <= duration + 0.002 or start < previous_start:
                raise ValueError("Некорректные таймкоды распознавания речи")
            if not isinstance(item["text"], str):
                raise ValueError("Некорректный текст распознавания речи")
            previous_start = start


def _safe(time: float, words: list[dict]) -> bool:
    return not any(w["start"] + 0.002 < time < w["end"] - 0.002 for w in words)


def _expand(start: float, end: float, segments: list[dict], words: list[dict], duration: float):
    # Include complete replies that cross a selected scene boundary.
    changed = True
    while changed:
        changed = False
        for item in [*segments, *words]:
            if item["start"] < start < item["end"]:
                start, changed = item["start"], True
            if item["start"] < end < item["end"]:
                end, changed = item["end"], True
    speech = [*segments, *words]
    beginnings = [s['start'] for s in speech if start - .002 <= s['start'] < end]
    if beginnings and min(beginnings) - start < .12:
        first = min(beginnings)
        start = min(start, _speech_lead(first, speech))
    end = _speech_tail(end, speech, duration)
    return max(0.0, start), min(duration, end)


def _speech_lead(start, speech):
    preceding = [s['end'] for s in speech if s['end'] <= start + .002]
    return min(start, max(0.0, start - SPEECH_LEAD, max(preceding, default=-1) + .04))


def _speech_tail(end, speech, duration):
    """ASR word ends can precede audible consonants by hundreds of ms."""
    endings = [s['end'] for s in speech if s['end'] <= end + .002]
    if not endings or end - max(endings) >= .12:
        return end
    if any(s['start'] <= end + .002 and s['end'] > end + .002 for s in speech):
        return end
    last = max(endings)
    following = [s['start'] for s in speech if s['start'] > end + .002]
    available = min(following, default=duration) - .04 if following else duration
    return max(end, min(last + SPEECH_TAIL, available, duration))


def _part_boundaries(intervals, events, segments, words, shots, duration):
    """Choose a path on retained OUTPUT time; meaning outweighs length balance."""
    total = sum(r['end'] - r['start'] for r in intervals)
    if total <= MAX_DURATION + 1e-7:
        return [(total, None)]
    candidates = {0.0: (0, None)}

    def add(time, cost, evidence=None):
        if not _safe(time, words):
            return
        crossing = [s for s in segments if s['start'] < time < s['end']]
        if any(s['end'] - s['start'] <= MAX_DURATION for s in crossing):
            return
        # A recognised reply longer than the ceiling can only be split at a
        # word boundary, with an explicit warning rather than a fake ending.
        if crossing:
            if not any(abs(w['end'] - time) < .002 for w in words):
                return
            cost, evidence = 60, None
        elapsed = 0.0
        for interval in intervals:
            if interval['start'] < time <= interval['end']:
                # Keep the complete selected speech handle before a source
                # gap. Otherwise an ASR tail 60ms before the selected end
                # leaves an orphan consonant at the start of the next part.
                if (0 < interval['end'] - time <= .75 and _safe(interval['end'], words)
                        and not any(time < s['start'] < interval['end'] or s['start'] < interval['end'] < s['end']
                                    for s in segments)):
                    time = interval['end']
                    if evidence:
                        evidence = {**evidence, 'time': time,
                                    'output_time': round(elapsed + time - interval['start'], 6)}
                output_time = round(elapsed + time - interval['start'], 6)
                if output_time not in candidates or cost < candidates[output_time][0]:
                    candidates[output_time] = (cost, evidence)
                return
            elapsed += interval['end'] - interval['start']

    for event in events:
        for ending in event.get('part_endings', []):
            add(ending['time'], {'closure': 0, 'cliffhanger': 1, 'transition': 3}[ending['kind']], ending)
    for segment in segments:
        add(_speech_tail(segment['end'], [*segments, *words], duration), 12)
        add(_speech_lead(segment['start'], [*segments, *words]), 15)
    for shot in shots:
        add(shot['start'], 16)
    for interval in intervals:
        add(interval['end'], 18)
    for word in words:
        add(word['end'], 60)
    # Legacy/silent analyses have no semantic evidence. Supply safe fallback
    # points without forcing the new analysis to follow an arithmetic grid.
    count = math.ceil(total / TARGET_DURATION)
    fallback = {total * i / count for i in range(1, count)}
    minimum_count = math.ceil(total / MAX_DURATION)
    fallback.update(total * i / minimum_count for i in range(1, minimum_count))
    fallback.update(float(t) for t in range(15, math.ceil(total), 15))
    for output_time in sorted(fallback):
        elapsed = 0.0
        for interval in intervals:
            span = interval['end'] - interval['start']
            if elapsed < output_time <= elapsed + span:
                add(interval['start'] + output_time - elapsed, 22)
                break
            elapsed += span
    total = round(total, 6)
    candidates[total] = (0, None)
    times = sorted(candidates)
    scores, previous = {0.0: 0.0}, {}
    for i, end in enumerate(times[1:], 1):
        choices = []
        for start in reversed(times[:i]):
            length = end - start
            if length > MAX_DURATION + 1e-6:
                break
            if length < .1 or start not in scores:
                continue
            length_cost = ((length - TARGET_DURATION) / 35) ** 2 + (max(0, 60 - length) / 12) ** 2
            choices.append((scores[start] + length_cost + candidates[end][0], start))
        if choices:
            scores[end], previous[end] = min(choices)
    if total not in scores:
        raise ValueError(f'Нельзя разделить реплику на части до {MAX_DURATION:g} секунд без обрыва слова')
    boundaries, time = [], total
    while time > 0:
        boundaries.append((time, candidates[time][1]))
        time = previous[time]
    return list(reversed(boundaries))


def build_plan(analysis: dict) -> dict:
    validate_analysis(analysis)
    from .source_roles import apply_exclusions,confirmed_exclusions
    events, probe = apply_exclusions(analysis["events"]), analysis["probe"]
    words = analysis["transcript"].get("words", [])
    segments = analysis["transcript"].get("segments", [])
    shot_starts = [_number(shot["start"]) for shot in analysis.get("shots", [])]
    if segments and not words:
        raise ValueError("Распознавание должно содержать временные отметки слов")
    by_id = {event["id"]: event for event in events}
    selected = {e["id"] for e in events if not e.get('pacing_excluded') and not e.get('global_excluded')
                and ((e["kind"] == "story" and e["importance"] >= 3) or e["importance"] >= 4)}
    # Uncertain analysis should preserve the episode rather than delete its story.
    warnings = [f"{event['id']}: {warning}" for event in events for key in ("focus_warnings", "story_warnings")
                for warning in event.get(key, []) if isinstance(warning, str)]
    warnings.extend(warning for warning in analysis.get('warnings', []) if isinstance(warning, str))
    if not selected:
        selected = {e["id"] for e in events if e["kind"] == "story"
                    and not e.get('global_excluded') and not e.get('pacing_excluded')}
        warnings.append("Важность событий не определена уверенно: сохранены все сюжетные сцены")
    if not selected:
        raise ValueError("В серии не найдены сюжетные сцены; проверьте анализ")
    pending = list(selected)
    while pending:
        for dep in by_id[pending.pop()].get("requires", []):
            if dep not in selected:
                selected.add(dep)
                pending.append(dep)
    intervals = []
    excluded_ranges = [r for event in events for r in confirmed_exclusions(event)]
    from .titles import _subtract
    for event in events:
        if event["id"] not in selected:
            continue
        selections = list(event.get("selected_ranges") or [event])
        # Legacy/fallback ranges have no validated omission partition: restore
        # their replies. Explicit whole-unit selections may omit redundant
        # exchanges; expand only selected replies and their speech handles.
        if (event['kind'] == 'story' and not event.get('credit_montage') and not event.get('pacing_excluded')
                and event.get('unit_selection_version') != 1):
            selections.extend(s for s in [*segments, *words]
                              if s['start'] < event['end'] and s['end'] > event['start'])
        for selection in sorted(selections, key=lambda s: s['start']):
            start, end = _expand(selection["start"], selection["end"], segments, words, probe["duration"])
            for piece in _subtract([{'start':start,'end':end}], excluded_ranges):
                left, right = piece['start'], piece['end']
                if intervals and left <= intervals[-1]["end"] + 0.002:
                    intervals[-1]["end"] = max(right, intervals[-1]["end"])
                    if event["id"] not in intervals[-1]["event_ids"]:
                        intervals[-1]["event_ids"].append(event["id"])
                else:
                    intervals.append({"start":left,"end":right,"event_ids":[event['id']]})
    boundaries = _part_boundaries(intervals, events, segments, words, analysis.get('shots', []), probe['duration'])
    parts, current = [], []
    current_duration, elapsed = 0.0, 0.0
    def finish():
        nonlocal current, current_duration
        if current:
            cues = make_cues(remap_words(words, current))
            ending = boundaries[len(parts)][1]
            part = {"index": len(parts) + 1, "duration": round(current_duration, 6), "cuts": current, "subtitles": cues}
            if ending:
                part['ending'] = dict(ending)
            elif len(parts) < len(boundaries) - 1:
                time = current[-1]['end']
                forced = any(s['start'] < time < s['end'] for s in segments)
                warnings.append((f'Длинная реплика разделена без обрыва слова в {time:.3f} с' if forced else
                                 f'Концовка в {time:.3f} с выбрана по целой реплике/плану; смысловая завершённость не подтверждена'))
            parts.append(part)
        current, current_duration = [], 0.0
    for interval in intervals:
        start = interval["start"]
        while start < interval["end"] - 1e-7:
            room = boundaries[len(parts)][0] - elapsed
            end = min(interval['end'], start + room)
            ids = [e["id"] for e in events if e["start"] < end and e["end"] > start]
            anchors = sorted([dict(a) for e in events if e["id"] in ids for a in e.get("focus", [])
                              if start <= a["time"] <= end], key=lambda a: a["time"])
            if not anchors:
                preceding = [a for e in events for a in e.get("focus", []) if a["time"] <= start]
                anchor = max(preceding, key=lambda a: a["time"]) if preceding else {"x": 0.5, "y": 0.5, "confidence": 0.0}
                anchors = [{**anchor, "time": start}]
            # A crop transition must not anticipate the composition of a shot
            # which is not visible yet. Reply anchors inside a shot still pan.
            for anchor in anchors:
                anchor['time'] = min(round(end, 6), max(round(start, 6), round(anchor['time'], 6)))
                anchor["hard_cut"] = any(abs(anchor["time"] - boundary) <= 0.002 + 1e-9
                                         for boundary in shot_starts)
            current.append({"start": round(start, 6), "end": round(end, 6), "event_ids": ids, "focus": anchors})
            current_duration += end - start
            elapsed += end - start
            start = end
            if elapsed >= boundaries[len(parts)][0] - 1e-6:
                finish()
    finish()
    retained_ids = {identifier for part in parts for cut in part["cuts"] for identifier in cut["event_ids"]}
    plan = {"schema_version": SCHEMA_VERSION, "source": {key: probe[key] for key in ("duration", "width", "height")},
            "selected_event_ids": [e["id"] for e in events if e["id"] in selected],
            "events": [dict(e) for e in events if e["id"] in retained_ids],
            "parts": parts, "warnings": list(dict.fromkeys(warnings))}
    validate_plan(plan, analysis)
    return plan


def validate_plan(plan: dict, analysis: dict) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION or not plan.get("parts"):
        raise ValueError("Неизвестный или пустой монтажный план")
    ids = {e["id"] for e in analysis["events"]}
    previous = -1.0
    for index, part in enumerate(plan["parts"], 1):
        if part["index"] != index or not part["cuts"]:
            raise ValueError("Некорректная последовательность частей")
        duration = 0.0
        for cut in part["cuts"]:
            start, end = _number(cut["start"]), _number(cut["end"])
            if not 0 <= start < end <= analysis["probe"]["duration"] + 0.002 or start < previous - 1e-6:
                raise ValueError("Монтаж повторяет, переставляет или выдумывает материал")
            if not cut["event_ids"] or any(i not in ids for i in cut["event_ids"]):
                raise ValueError("Неизвестное исходное событие")
            for anchor in cut["focus"]:
                if not start <= _number(anchor["time"]) <= end or any(not 0 <= _number(anchor[k]) <= 1 for k in ("x", "y", "confidence")):
                    raise ValueError("Некорректное кадрирование в плане")
                if "hard_cut" in anchor and not isinstance(anchor["hard_cut"], bool):
                    raise ValueError("Некорректный признак смены кадра")
            previous, duration = end, duration + end - start
        if duration > MAX_DURATION + 1e-6 or abs(duration - _number(part["duration"])) > 1e-5:
            raise ValueError(f"Часть превышает {MAX_DURATION:g} секунд или имеет неверную длительность")
        from .editing import validate_options
        options = validate_options(part.get('layout', 'portrait'), part.get('caption_style', 'classic'))
        expected = make_cues(remap_words(analysis["transcript"].get("words", []), part["cuts"]), options['caption_style'])
        if part["subtitles"] != expected:
            raise ValueError("Субтитры не соответствуют исходным словам и монтажу")
