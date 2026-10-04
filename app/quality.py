"""Plan diagnostics clipped to footage that is present in the final export."""
from __future__ import annotations

import re
import math

_EVENT_ID = re.compile(r"^(event_\d{4,}):\s*(.*)$")
_UNIT_WARNING = re.compile(r"^([a-z]\d{3,}):\s*(.*)$", re.I)
_PROFILE = re.compile(r"(?:(?:сохранен|сохранена|сохранено|сохранены|атмосфер).{0,100}(?:профил|настроек)|профил.{0,80}сохранен)", re.I)


def _range(value):
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("start"), bool) or isinstance(value.get("end"), bool):
        return None
    try:
        start, end = float(value["start"]), float(value["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return (start, end) if math.isfinite(start) and math.isfinite(end) and 0 <= start < end else None


def _intersections(left, right):
    return [(max(a, c), min(b, d)) for a, b in left for c, d in right if max(a, c) < min(b, d)]


def _final_ranges(plan):
    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        return None
    ranges = []
    for part in parts:
        cuts = part.get("cuts") if isinstance(part, dict) else None
        if not isinstance(cuts, list):
            return None
        for cut in cuts:
            interval = _range(cut)
            if interval is None:
                return None
            ranges.append(interval)
    source = plan.get("source")
    if isinstance(source, dict) and source.get("duration") is not None:
        try:
            duration = float(source["duration"])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(duration) or duration <= 0 or any(end > duration + .002 for _, end in ranges):
            return None
    return ranges


def _event_kept(event, final):
    selected = event.get("selected_ranges")
    if not isinstance(selected, list):
        return None
    source = []
    for item in selected:
        interval = _range(item)
        if interval is None:
            return None
        source.append(interval)
    event_id = event.get("id")
    attributed = []
    has_attribution = False
    for part in event.get("_parts", []):
        for cut in part.get("cuts", []):
            ids = cut.get("event_ids")
            if isinstance(ids, list):
                has_attribution = True
                if event_id in ids and (interval := _range(cut)):
                    attributed.append(interval)
    return _intersections(source, attributed if has_attribution else final)


def _event_unit_ranges(event):
    """Return unambiguous unit IDs backed by exact source intervals."""
    result, conflicts = {}, set()

    def take(row):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            return
        interval = _range(row)
        if isinstance(event.get("start"), bool) or isinstance(event.get("end"), bool):
            return
        try:
            event_start, event_end = float(event["start"]), float(event["end"])
        except (KeyError, TypeError, ValueError):
            return
        if (not interval or not math.isfinite(event_start) or not math.isfinite(event_end)
                or not event_start <= interval[0] < interval[1] <= event_end):
            return
        unit_id = row["id"]
        if unit_id in result and result[unit_id] != interval:
            conflicts.add(unit_id)
        else:
            result[unit_id] = interval

    for row in event.get("diagnostic_unit_ranges", []) if isinstance(event.get("diagnostic_unit_ranges"), list) else []:
        take(row)
    review = event.get("story_omission_review")
    if isinstance(review, dict) and isinstance(review.get("verified_units"), list):
        for row in review["verified_units"]:
            take(row)
    for key in ("omitted_story_units", "pacing_removed"):
        rows = event.get(key)
        if isinstance(rows, list):
            for row in rows:
                take(row)
    return {unit_id: interval for unit_id, interval in result.items() if unit_id not in conflicts}


def summarize_plan(plan: dict) -> dict:
    """Return actionable warnings and separate informational retention notes."""
    final = _final_ranges(plan)
    if final is None:
        return {"available": False, "warnings": [], "notes": []}
    events = {e.get("id"): {**e, "_parts": plan["parts"]} for e in plan.get("events", [])
              if isinstance(e, dict) and isinstance(e.get("id"), str)}
    warnings, notes = [], []
    seen = set()
    for raw in plan.get("warnings", []):
        if not isinstance(raw, str) or not raw.strip():
            continue
        match = _EVENT_ID.match(raw)
        event_id, text = (match.group(1), match.group(2)) if match else (None, raw.strip())
        event = events.get(event_id) if event_id else None
        kept = _event_kept(event, final) if event else None
        if event_id and (event is None or kept is None or not kept):
            continue
        unit_match = _UNIT_WARNING.match(text)
        unit_id = unit_match.group(1) if unit_match else None
        warning_text = unit_match.group(2) if unit_match else text
        mapped = _event_unit_ranges(event).get(unit_id) if event and unit_id else None
        if unit_id and mapped and not _intersections([mapped], kept):
            continue
        row = {"text": (warning_text if mapped else text)[:500], "event_id": event_id}
        if unit_id:
            row["unit_id"] = unit_id
        if unit_id and event and mapped is None:
            row["category"] = "uncertainty"
            key = (event_id, unit_id, warning_text)
            if key not in seen:
                seen.add(key)
                warnings.append(row)
        elif _PROFILE.search(warning_text):
            row["category"] = "profile"
            notes.append(row)
        else:
            row["category"] = "uncertainty" if event and (event.get("uncertain") or event.get("selection_uncertain")) else "review"
            key = (event_id, unit_id, warning_text)
            if key not in seen:
                seen.add(key)
                warnings.append(row)
    return {"available": True, "warnings": warnings[:200], "notes": notes[:200]}


def debug_timeline(plan: dict) -> dict:
    """Expose only source intervals with explicit retained-unit provenance."""
    final = _final_ranges(plan)
    if final is None:
        return {"available": False, "reasons": []}
    events = plan.get("events")
    if not isinstance(events, list) or not events:
        return {"available": False, "reasons": []}
    events = [{**event, "_parts": plan["parts"]} for event in events if isinstance(event, dict)]
    reasons = []
    evidence_seen = False

    def add(event, source_ranges, kind, title, detail=""):
        nonlocal evidence_seen
        if not source_ranges:
            return
        evidence_seen = True
        kept = _event_kept(event, final)
        if kept is None:
            return
        for start, end in _intersections(source_ranges, kept):
            reasons.append({"start": start, "end": end, "kind": kind, "title": title,
                            "detail": detail[:500], "event_id": event.get("id", "")})

    for event in events:
        if not isinstance(event, dict):
            continue
        if not isinstance(event.get("selected_ranges"), list):
            return {"available": False, "reasons": []}
        atmo = [r for x in event.get("protected_atmosphere_ranges", []) if (r := _range(x))]
        if atmo:
            add(event, atmo, "atmosphere", "Причина модели: атмосфера",
                "Это пометка сохранённого анализа, а не независимая проверка эмоционального смысла.")
        review = event.get("story_omission_review")
        if isinstance(review, dict):
            verified = review.get("verified_units", [])
            decisions = {d.get("unit"): d for d in (review.get("decision", {}).get("decisions", [])
                         if isinstance(review.get("decision"), dict) else []) if isinstance(d, dict)}
            for unit in verified if isinstance(verified, list) else []:
                interval = _range(unit)
                decision = decisions.get(unit.get("id")) if isinstance(unit, dict) else None
                if (not interval or not decision or decision.get("current_episode_story") is not True
                        or type(decision.get("story_change")) is not bool
                        or type(decision.get("reaction_or_humor")) is not bool):
                    continue
                confidence = decision.get("confidence")
                if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                        or not math.isfinite(confidence) or confidence < .9):
                    continue
                reaction = decision["reaction_or_humor"]
                if not decision["story_change"] and not reaction:
                    continue
                kind = "reaction" if reaction else "story"
                title = "Проверенная реакция" if reaction else "Подтверждённое изменение сюжета"
                evidence = decision.get("evidence")
                if not isinstance(evidence, str) or not evidence.strip():
                    continue
                add(event, [interval], kind, title, evidence)
        if event.get("selection_uncertain") or event.get("uncertain"):
            selected = [r for x in event.get("selected_ranges", []) if (r := _range(x))]
            add(event, selected, "uncertainty", "Оставлено из-за неопределённости",
                "Анализ пометил событие как неопределённое; проверьте этот фрагмент.")

        manual = event.get("manual_editorial_review")
        manual_ranges = []
        if isinstance(manual, dict):
            candidates = manual.get("ranges")
            if isinstance(candidates, list):
                manual_ranges = [interval for item in candidates if (interval := _range(item))]
            elif (interval := _range(manual)):
                manual_ranges = [interval]
        if manual_ranges:
            add(event, manual_ranges, "manual", "Проверено вручную",
                str(manual.get("reason", "Решение монтажёра.")) if isinstance(manual, dict) else "Решение монтажёра.")

    reasons.sort(key=lambda item: (item["start"], item["end"], item["kind"]))
    return {"available": evidence_seen, "reasons": reasons[:500] if evidence_seen else []}
