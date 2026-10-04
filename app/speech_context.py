"""Restore verified ASR prefixes whose omission can reverse a retained reply."""
from __future__ import annotations

import copy
import math
import re

PREFIX_WORDS = {
    "не", "ни", "что", "как", "почему", "зачем", "где", "куда", "откуда", "когда", "кто",
    "какой", "какая", "какие", "сколько", "разве", "неужели", "и", "а", "но", "если", "чтобы",
    "потому", "хотя", "или", "либо", "зато", "пока", "ведь", "да",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", str(text).casefold().replace("ё", "е"), flags=re.UNICODE)


def _retained(events: list[dict]) -> set[str]:
    by_id = {event["id"]: event for event in events}
    retained = {event["id"] for event in events if not event.get('global_excluded')
                and ((event["kind"] == "story" and event["importance"] >= 3) or event["importance"] >= 4)}
    if not retained:
        retained = {event["id"] for event in events if event["kind"] == "story"
                    and not event.get('global_excluded') and not event.get('pacing_excluded')}
    pending = list(retained)
    while pending:
        for dependency in by_id[pending.pop()].get("requires", []):
            if dependency in by_id and dependency not in retained:
                retained.add(dependency)
                pending.append(dependency)
    return retained


def _ranges(event: dict) -> list[dict]:
    return event.get("selected_ranges") or [{"start": event["start"], "end": event["end"]}]


def _selected(words: list[dict], segment: dict, events: list[dict], retained: set[str]) -> bool:
    speech = [word for word in words if word["start"] < segment["end"] and word["end"] > segment["start"]]
    # Word evidence is mandatory; selecting empty margin/silence is insufficient.
    return any(word["start"] < interval["end"] and word["end"] > interval["start"]
               for event in events if event["id"] in retained for interval in _ranges(event) for word in speech)


def _merge(intervals: list[dict]) -> list[dict]:
    merged = []
    for interval in sorted(intervals, key=lambda value: (value["start"], value["end"])):
        value = {"start": interval["start"], "end": interval["end"]}
        if merged and value["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], value["end"])
        else:
            merged.append(value)
    return merged


def protect_question_pairs(events: list[dict], transcript: dict) -> list[dict]:
    """Retained answers must retain their adjacent actual source question."""
    result = copy.deepcopy(events)
    retained = _retained(result)
    words = transcript.get('words', [])
    segments = sorted(transcript.get('segments', []), key=lambda item: item['start'])
    for question, answer in zip(segments, segments[1:]):
        if not re.search(r'\?\s*[\"\'»”)]*$', str(question.get('text', ''))):
            continue
        gap = float(answer['start']) - float(question['end'])
        if not math.isfinite(gap) or not 0 <= gap <= 5:
            continue
        speech = [word for word in words if word['start'] < question['end'] and word['end'] > question['start']]
        if not speech or sum(float(w.get('probability', 1)) for w in speech) / len(speech) < .65:
            continue
        if not _selected(words, answer, result, retained) or _selected(words, question, result, retained):
            continue
        left, right = min(w['start'] for w in speech), max(w['end'] for w in speech)
        if not all(math.isfinite(v) for v in (left, right)) or left >= right:
            continue
        for event in result:
            if event.get('credit_montage') or event['start'] >= right or event['end'] <= left:
                continue
            existing = _ranges(event) if event['id'] in retained else []
            event['selected_ranges'] = _merge([*existing, {
                'start': round(max(event['start'], left - .25), 6),
                'end': round(min(event['end'], right + .3), 6)}])
            event['importance'] = max(4, event['importance'])
            event.pop('global_excluded', None)
            retained.add(event['id'])
            protection = {'question': question['text'], 'start': left, 'end': right,
                          'answer_start': answer['start'], 'answer_end': answer['end']}
            event.setdefault('question_pair_protections', []).append(protection)
            event.setdefault('story_warnings', []).append('Для выбранного ответа восстановлен исходный вопрос: ' + question['text'])
    return result


def protect_speech_context(events: list[dict], transcript: dict) -> list[dict]:
    """Deep-copy events and add only prefixes verified against one raw utterance."""
    result = copy.deepcopy(events)
    raw_segments = transcript.get("raw_segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return protect_question_pairs(result, transcript)
    segments = sorted(transcript.get("segments", []), key=lambda segment: segment["start"])
    words = transcript.get("words", [])
    retained = _retained(result)
    for prefix, continuation in zip(segments, segments[1:]):
        text = str(prefix.get("text", "")).strip()
        tokens = _tokens(text)
        if (not 1 <= len(tokens) <= 2 or tokens[0] not in PREFIX_WORDS
                or re.search(r"[.!?…;:]\s*[\"'»”)]*$", text)):
            continue
        gap = float(continuation["start"]) - float(prefix["end"])
        if not math.isfinite(gap) or not 0 <= gap <= 15:
            continue
        if not _selected(words, continuation, result, retained) or _selected(words, prefix, result, retained):
            continue
        body = _tokens(continuation.get("text", ""))
        if not body:
            continue
        matching_raw = next((raw for raw in raw_segments if isinstance(raw, dict)
                             and raw.get("start", math.inf) <= prefix["start"] + 0.002
                             and raw.get("end", -math.inf) >= continuation["end"] - 0.002
                             and _tokens(raw.get("text", ""))[:len(tokens) + len(body)] == tokens + body), None)
        if matching_raw is None:
            continue
        prefix_words = [word for word in words if word["start"] < prefix["end"] and word["end"] > prefix["start"]]
        if [token for word in prefix_words for token in _tokens(word.get("text", ""))] != tokens:
            continue
        core_start = min(word["start"] for word in prefix_words)
        core_end = max(word["end"] for word in prefix_words)
        if not all(math.isfinite(float(value)) for value in (core_start, core_end)) or core_start >= core_end:
            continue
        for event in result:
            if event["start"] >= core_end or event["end"] <= core_start:
                continue
            left, right = max(event["start"], core_start - 0.15), min(event["end"], core_end + 0.15)
            existing = event.get("selected_ranges")
            if not existing:
                existing = _ranges(event) if event["id"] in retained else []
            event["selected_ranges"] = _merge([*existing, {"start": round(left, 6), "end": round(right, 6)}])
            event["importance"] = max(4, event["importance"])
            event.pop('global_excluded', None)
            retained.add(event["id"])
            protection = {"prefix": text, "start": core_start, "end": core_end,
                          "continuation_start": continuation["start"], "continuation_end": continuation["end"],
                          "raw_start": matching_raw["start"], "raw_end": matching_raw["end"], "gap_seconds": round(gap, 6)}
            protections = event.setdefault("speech_context_protections", [])
            if protection not in protections:
                protections.append(protection)
            if gap > 2:
                warning = (f"Разрыв ASR {gap:.2f} с между «{text}» и продолжением: восстановлен исходный смысловой префикс; "
                           "проверьте связность реплики")
                for key in ("speech_context_warnings", "story_warnings"):
                    warnings = event.setdefault(key, [])
                    if warning not in warnings:
                        warnings.append(warning)
    return protect_question_pairs(result, transcript)
